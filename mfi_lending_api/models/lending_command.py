"""Every write Odoo sends to the lending service, and its key (DECISIONS D-006, D-012).

A row is written on a cursor of its own, before the call and again after it, so
the key survives whatever happens to the person's transaction: a retry of the
same action (same operation, record and body) reuses it, and the service
answers the first result instead of acting twice. A changed body is a new
action, with a new key.

Rows hold references only: no body, no name, no number, no file.
"""

import hashlib
import json
import logging
import time
import uuid
from datetime import timedelta

from odoo import SUPERUSER_ID, api, fields, models

from ..services.errors import LendingError, LendingRefusal, LendingUnavailable

_logger = logging.getLogger(__name__)

RETENTION_DAYS = 396  # 13 months (staff-workspace §7)
IN_PROGRESS_RETRIES = (1, 2, 4)  # seconds to wait on 409 request_in_progress


def body_hash(operation, lending_ref, body):
    canonical = json.dumps([operation, lending_ref or "", body], sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class MfiLendingCommand(models.Model):
    _name = "mfi.lending.command"
    _description = "Lending service command"
    _order = "id desc"
    _log_access = True

    operation = fields.Char(required=True, index=True, readonly=True)
    res_model = fields.Char("Odoo model", readonly=True, index=True)
    res_id = fields.Integer("Odoo record", readonly=True, index=True)
    lending_ref = fields.Char("Lending service id", readonly=True, index=True,
                              help="The lending service's id for the record the command acts on, or created.")
    idempotency_key = fields.Char(required=True, readonly=True, index=True)
    body_hash = fields.Char(required=True, readonly=True, index=True)
    state = fields.Selection([
        ("pending", "Sent, no answer yet"),
        ("accepted", "Accepted"),
        ("refused", "Refused"),
        ("unavailable", "Service unavailable"),
    ], required=True, default="pending", readonly=True, index=True)
    http_status = fields.Integer(readonly=True)
    code = fields.Char("Refusal code", readonly=True)
    trace_id = fields.Char("Trace id", readonly=True)
    attempts = fields.Integer(default=0, readonly=True)
    user_id = fields.Many2one("res.users", "By", readonly=True, index=True)

    # ------------------------------------------------------------------
    # Running a command
    # ------------------------------------------------------------------

    @api.model
    def _run(self, operation, record, body, call, lending_ref=None):
        """Send one command and record it.

        ``call(key)`` does the HTTP and returns a ``LendingResponse``. Returns
        that response; raises ``LendingRefusal`` or ``LendingUnavailable``.
        """
        digest = body_hash(operation, lending_ref, body)
        res_model, res_id = (record._name, record.id) if record else (False, 0)
        row_id, key = self._open(operation, res_model, res_id, lending_ref, digest)
        waits = list(IN_PROGRESS_RETRIES)
        while True:
            try:
                response = call(key)
            except LendingRefusal as error:
                if error.code == "request_in_progress" and waits:
                    self._sleep(waits.pop(0))
                    continue
                self._close(row_id, "refused", error.status, error.code, error.trace_id)
                raise
            except LendingUnavailable as error:
                self._close(row_id, "unavailable", error.status, error.code, error.trace_id)
                raise
            except LendingError as error:
                # Not set up: nothing was sent.
                self._close(row_id, "unavailable", None, error.code, None)
                raise
            created = (response.data or {}).get("id") if isinstance(response.data, dict) else None
            self._close(row_id, "accepted", response.status, False, False,
                        lending_ref=lending_ref or created)
            return response

    @api.model
    def _sleep(self, seconds):
        time.sleep(seconds)

    def _own_env(self, cr):
        return api.Environment(cr, SUPERUSER_ID, {})

    @api.model
    def _open(self, operation, res_model, res_id, lending_ref, digest):
        """Find the key of an unfinished identical action, or make a new one; record the attempt."""
        user_id = self.env.uid
        with self.env.registry.cursor() as cr:
            # One opener at a time for the same action: two quick clicks share one key.
            cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [digest])
            env = self._own_env(cr)
            Command = env[self._name]
            previous = Command.search([
                ("operation", "=", operation),
                ("res_model", "=", res_model),
                ("res_id", "=", res_id),
                ("body_hash", "=", digest),
                ("state", "in", ("pending", "unavailable")),
            ], limit=1)
            if previous:
                previous.write({"state": "pending", "attempts": previous.attempts + 1, "user_id": user_id})
                return previous.id, previous.idempotency_key
            row = Command.create({
                "operation": operation,
                "res_model": res_model,
                "res_id": res_id,
                "lending_ref": lending_ref,
                "idempotency_key": str(uuid.uuid4()),
                "body_hash": digest,
                "attempts": 1,
                "user_id": user_id,
            })
            return row.id, row.idempotency_key

    @api.model
    def _close(self, row_id, state, http_status, code, trace_id, lending_ref=None):
        try:
            with self.env.registry.cursor() as cr:
                values = {"state": state, "http_status": http_status or 0,
                          "code": code or False, "trace_id": trace_id or False}
                if lending_ref:
                    values["lending_ref"] = lending_ref
                self._own_env(cr)[self._name].browse(row_id).write(values)
        except Exception:  # the outcome stands even if its record cannot be written
            _logger.warning("Could not record the outcome of lending command %s", row_id, exc_info=True)

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------

    @api.model
    def _cron_purge(self):
        cutoff = fields.Datetime.now() - timedelta(days=RETENTION_DAYS)
        old = self.sudo().search([("create_date", "<", cutoff)])
        _logger.info("Removing %d lending commands older than %d days", len(old), RETENTION_DAYS)
        old.unlink()
