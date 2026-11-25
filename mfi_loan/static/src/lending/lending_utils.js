import { _t } from "@web/core/l10n/translation";
import { formatDateTime } from "@web/core/l10n/dates";

const { DateTime } = luxon;

/** "fetched at" and other times from the lending service (ISO 8601, UTC). */
export function formatWhen(iso) {
    if (!iso) {
        return "";
    }
    const value = DateTime.fromISO(iso, { zone: "utc" });
    return value.isValid ? formatDateTime(value.setZone("default")) : iso;
}

export const STATE_LABELS = {
    DRAFT: _t("Draft"),
    VERIFYING: _t("Checks running"),
    VERIFIED: _t("Verified"),
    ACTIVE: _t("Active"),
    HELD: _t("Under review"),
    LAPSED: _t("Lapsed"),
};

export const STATE_TONES = {
    DRAFT: "secondary",
    VERIFYING: "info",
    VERIFIED: "success",
    ACTIVE: "success",
    HELD: "warning",
    LAPSED: "dark",
};

export const DOCUMENT_LABELS = {
    ID_DOCUMENT: _t("ID document"),
    CLIENT_PHOTO: _t("Client photo"),
    KRA_PIN_CERTIFICATE: _t("KRA PIN certificate"),
};

export const DOCUMENT_STATES = {
    AWAITING_UPLOAD: _t("Waiting for the file"),
    RECEIVED: _t("Received, being checked"),
    STORED: _t("Stored"),
    REJECTED: _t("Rejected"),
};

export const CHECK_LABELS = {
    REGISTER: _t("Identity register"),
    KRA_PIN: _t("KRA PIN"),
    SCREENING: _t("Screening"),
    PHOTO: _t("Photo"),
};

export const OUTCOME_LABELS = {
    PENDING: _t("Waiting"),
    RUNNING: _t("Running"),
    PASSED: _t("Passed"),
    CORRECTION_NEEDED: _t("Correction needed"),
    REGISTER_UNAVAILABLE: _t("Register unavailable, retrying"),
};

export const OUTCOME_TONES = {
    PENDING: "secondary",
    RUNNING: "info",
    PASSED: "success",
    CORRECTION_NEEDED: "warning",
    REGISTER_UNAVAILABLE: "warning",
};

export const FIELD_LABELS = {
    firstName: _t("First name"),
    middleName: _t("Middle name"),
    lastName: _t("Last name"),
    idNumber: _t("ID number"),
    dateOfBirth: _t("Date of birth"),
    kraPin: _t("KRA PIN"),
    phone: _t("Phone"),
    email: _t("Email"),
};

export function documentLabel(type) {
    return DOCUMENT_LABELS[type] || type;
}

export function checklistLabel(item) {
    if (item === "consent_to_checks") {
        return _t("Consent to checks");
    }
    if (item === "phone_confirmed") {
        return _t("Phone confirmed");
    }
    if (item.startsWith("document:")) {
        return documentLabel(item.slice("document:".length));
    }
    return item;
}

/** A File as base64, without the "data:...;base64," prefix. */
export function readAsBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
    });
}
