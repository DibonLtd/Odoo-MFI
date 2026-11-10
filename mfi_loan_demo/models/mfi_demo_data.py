"""The sample data: Kenyan clients, what they pledge, and what happens to each loan.

Names, places and businesses are typical of Roan Capital's market; the people
are made up. Email addresses use example.com, which never delivers.
"""

# The portal's staff accounts, one per role, at a demo subdomain so they never
# clash with real staff logins.
STAFF = [
    ("admin", "System Administrator", "admin"),
    ("credit", "Grace Wanjiru", "credit_manager"),
    ("credit2", "Mary Njeri", "credit_manager"),
    ("headoffice", "Peter Kiprotich", "head_office"),
    ("ceo", "Daniel Mwaura", "ceo"),
    ("finance", "Faith Achieng", "finance"),
    ("officer", "Brian Otieno", "loan_officer"),
    ("collections", "Janet Nyokabi", "collections"),
    ("auditor", "Samuel Ruto", "auditor"),
]
STAFF_DOMAIN = "demo.roancapital.co.ke"

# name, business type, business location, home, county, daily income, stock value
INDIVIDUALS = [
    ("Wanjiku Kamau", "Mitumba (second-hand clothes)", "Gikomba Market, Nairobi", "Kayole, Nairobi", "Nairobi", 4500, 120000),
    ("Otieno Odhiambo", "Fish vendor", "Kibuye Market, Kisumu", "Nyalenda, Kisumu", "Kisumu", 3800, 45000),
    ("Achieng Atieno", "Salon", "Kondele, Kisumu", "Kondele, Kisumu", "Kisumu", 2500, 30000),
    ("Kipchoge Kiprono", "Agrovet", "Eldoret town", "Langas, Eldoret", "Uasin Gishu", 6500, 250000),
    ("Njeri Wambui", "Mama mboga (groceries)", "Makongeni Market, Thika", "Makongeni, Thika", "Kiambu", 1800, 15000),
    ("Mutua Nzioka", "Boda boda", "Mlolongo stage", "Mlolongo", "Machakos", 2200, 0),
    ("Akinyi Onyango", "Food kiosk", "Olympic, Kibera", "Kibera, Nairobi", "Nairobi", 2000, 12000),
    ("Mwangi Kariuki", "Hardware", "Githurai 45", "Githurai 45", "Kiambu", 9000, 600000),
    ("Chebet Jepkosgei", "Tailoring", "Kericho town", "Kapsoit, Kericho", "Kericho", 1500, 40000),
    ("Barasa Wafula", "Cereals shop", "Bungoma Market", "Kanduyi, Bungoma", "Bungoma", 5000, 180000),
    ("Naliaka Nekesa", "M-Pesa agent", "Kakamega town", "Shirere, Kakamega", "Kakamega", 3000, 100000),
    ("Kimani Njoroge", "Butchery", "Top Market, Nakuru", "Lanet, Nakuru", "Nakuru", 7000, 60000),
    ("Mueni Ndunge", "Cosmetics shop", "Kitengela town", "Kitengela", "Kajiado", 2500, 70000),
    ("Hassan Abdi", "Electronics shop", "Eastleigh, Nairobi", "Eastleigh, Nairobi", "Nairobi", 12000, 900000),
    ("Gathoni Wairimu", "Milk bar", "Nyeri town", "Ruring'u, Nyeri", "Nyeri", 3500, 25000),
    ("Omondi Ochieng", "Eatery", "Homa Bay town", "Homa Bay", "Homa Bay", 4000, 30000),
    ("Kerubo Moraa", "Banana wholesale", "Daraja Mbili Market, Kisii", "Nyanchwa, Kisii", "Kisii", 3000, 50000),
    ("Juma Rashid", "Fruit wholesale", "Kongowea Market, Mombasa", "Kisauni, Mombasa", "Mombasa", 8000, 150000),
    ("Nyambura Kimani", "Poultry farming", "Ruiru", "Membley, Ruiru", "Kiambu", 5000, 220000),
    ("Kibet Korir", "Matatu owner", "Iten stage", "Iten", "Elgeyo Marakwet", 6000, 0),
    ("Zawadi Mwende", "Cyber café", "Embu town", "Majimbo, Embu", "Embu", 2800, 150000),
    ("Kamau Maina", "Welding workshop", "Kawangware 56", "Kawangware, Nairobi", "Nairobi", 3500, 80000),
    ("Cherono Langat", "Shoe shop", "Bomet town", "Silibwet, Bomet", "Bomet", 2000, 90000),
    ("Ochieng Owino", "Phone accessories", "Jubilee Market, Kisumu", "Manyatta, Kisumu", "Kisumu", 2500, 60000),
    ("Wambui Njuguna", "Chemist", "Kiambu town", "Ndumberi, Kiambu", "Kiambu", 6000, 300000),
    ("Kiprotich Rotich", "Car wash", "Free Area, Nakuru", "Free Area, Nakuru", "Nakuru", 3000, 20000),
]

# name, registration number, business type, location, director, designation, daily income, stock
BUSINESSES = [
    ("Gikomba Mitumba Traders", "BN-K7X2P9Q", "Mitumba wholesale", "Gikomba Market, Nairobi",
     "Joseph Kamau Ndegwa", "Proprietor", 25000, 1500000),
    ("Kahawa Hardware & Electricals Ltd", "PVT-AAB4K7Z", "Hardware and electricals", "Kahawa West, Nairobi",
     "Lucy Wanjiru Gitau", "Director", 40000, 3200000),
    ("Mama Pima Groceries", "BN-R3M8T2L", "Groceries", "Kariobangi North, Nairobi",
     "Esther Atieno Ouma", "Proprietor", 9000, 250000),
    ("Kisumu Fish Mongers Ltd", "PVT-QWE7781", "Fish wholesale", "Dunga Beach, Kisumu",
     "George Onyango Okoth", "Managing director", 35000, 400000),
]

KIN = [("Spouse", "Wife"), ("Spouse", "Husband"), ("Sibling", "Sister"), ("Sibling", "Brother"),
       ("Parent", "Mother"), ("Parent", "Father")]
OTHER_NAMES = ["Wanjiru", "Kiptoo", "Adhiambo", "Muthoni", "Ouma", "Nduta", "Kiplagat", "Wekesa",
               "Auma", "Njambi", "Mutiso", "Chepkoech", "Omollo", "Wangari", "Kirui", "Makena"]
BANKS = ["Equity Bank", "KCB Bank", "Co-operative Bank", "Family Bank", "NCBA Bank", "Absa Bank Kenya"]
SAFARICOM = ["0710", "0711", "0712", "0715", "0720", "0721", "0722", "0727", "0728", "0740",
             "0741", "0743", "0745", "0757", "0768", "0790", "0791", "0795", "0110", "0113", "0115"]
AIRTEL = ["0730", "0733", "0734", "0750", "0752", "0785", "0100", "0102"]

CHATTELS = [
    ("Fridge (Hotpoint 300L)", 1, 45000), ("Sofa set, 5 seater", 1, 38000), ("Sewing machine (Butterfly)", 2, 9000),
    ('Television, Hisense 43"', 1, 32000), ("Posho mill", 1, 85000), ("Display counter (glass)", 2, 15000),
    ("Gas cooker, 4 burner", 1, 28000), ("Water dispenser", 1, 12000), ("Deep freezer (Ramtons 200L)", 1, 52000),
    ("Hair dryer and salon chairs", 3, 8000), ("Laptop (HP ProBook)", 1, 45000), ("Welding machine", 1, 60000),
]
VEHICLES = [
    ("KDA 412M", "Toyota", "Probox", "2015"), ("KCZ 908P", "Toyota", "Fielder", "2014"),
    ("KDG 117C", "Nissan", "Note", "2016"), ("KCE 553H", "Isuzu", "NKR", "2013"),
    ("KMFA 231B", "Bajaj", "Boxer 150", "2021"), ("KDC 670T", "Toyota", "Hiace", "2017"),
    ("KDJ 245A", "Mitsubishi", "Canter", "2018"),
]
LAND = [
    "RUIRU/RUIRU EAST BLOCK 2/1543", "NAKURU MUNICIPALITY BLOCK 15/672", "KISUMU/KOGONY/2231",
    "MACHAKOS TOWN BLOCK 3/918", "KIAMBU/NDUMBERI/4410", "UASIN GISHU/KIMUMU/1187",
]

# One line per loan, in each client's order:
# (client, loan type, amount, term, what happens, disbursed this many days ago, details)
# What happens:
#   repaid       paid on time until closed
#   current      pays every day or two; nothing late
#   late         paid on time, then stopped `stopped` days ago
#   overdue      paid `paid_days` days, then stopped; now past maturity
#   settled      settled early `settle_after` days after disbursement
#   written_off  paid `paid_days` days; written off `written_off_ago` days ago
#   approved, stage1, stage2, stage3, pending_information, draft, rejected: not yet disbursed
LOANS = [
    (0, "chattels", 20000, "one_month", "repaid", 78, {}),
    (0, "chattels", 30000, "one_month", "current", 12, {}),
    (1, "logbook", 60000, "one_month", "current", 8, {}),
    (2, "chattels", 15000, "one_month", "late", 20, {"stopped": 4}),
    (3, "logbook", 80000, "one_month", "repaid", 64, {}),
    (3, "logbook", 100000, "one_month", "stage2", 0, {}),
    (4, "chattels", 8000, "two_weeks", "current", 6, {}),
    (5, "logbook", 45000, "one_month", "late", 22, {"stopped": 10}),
    (6, "chattels", 10000, "two_weeks", "overdue", 45, {"paid_days": 5}),
    (7, "title_deed", 100000, "one_month", "current", 15, {}),
    (8, "chattels", 12000, "two_weeks", "repaid", 52, {}),
    (8, "chattels", 18000, "one_month", "late", 14, {"stopped": 6}),
    (9, "chattels", 25000, "one_month", "late", 27, {"stopped": 18}),
    (10, "chattels", 40000, "one_month", "settled", 20, {"settle_after": 12}),
    (11, "logbook", 70000, "one_month", "current", 3, {}),
    (12, "chattels", 9000, "two_weeks", "written_off", 95, {"paid_days": 3, "written_off_ago": 30}),
    (13, "chattels", 50000, "one_month", "current", 24, {"reversal": True}),
    (14, "chattels", 10000, "one_month", "repaid", 72, {}),
    (14, "chattels", 15000, "two_weeks", "current", 9, {}),
    (15, "chattels", 30000, "one_month", "overdue", 40, {"paid_days": 12}),
    (16, "chattels", 6000, "two_weeks", "current", 2, {}),
    (17, "chattels", 35000, "one_month", "approved", 0, {}),
    (18, "title_deed", 90000, "one_month", "approved", 0, {}),
    (19, "logbook", 75000, "one_month", "stage1", 0, {}),
    (20, "chattels", 20000, "one_month", "stage3", 0, {}),
    (21, "chattels", 12000, "one_month", "pending_information", 0, {}),
    (22, "chattels", 7000, "two_weeks", "draft", 0, {}),
    (23, "title_deed", 60000, "one_month", "rejected", 0, {}),
    (24, "chattels", 22000, "one_month", "current", 18, {}),
    (25, "logbook", 40000, "one_month", "draft", 0, {}),
    (26, "chattels", 80000, "one_month", "current", 10, {}),
    (27, "title_deed", 100000, "one_month", "repaid", 58, {}),
    (27, "title_deed", 100000, "one_month", "current", 5, {}),
    (28, "chattels", 30000, "one_month", "pending_information", 0, {}),
    (29, "logbook", 90000, "one_month", "late", 25, {"stopped": 13}),
]

# ----------------------------------------------------------------------
# Other Odoo apps, loaded when they are installed
# ----------------------------------------------------------------------

# Extra access for the sample staff in the other apps (skipped when an app is absent).
STAFF_APP_GROUPS = {
    "admin": ["hr.group_hr_manager", "helpdesk.group_helpdesk_manager", "sales_team.group_sale_manager"],
    "credit": ["sales_team.group_sale_salesman_all_leads", "helpdesk.group_helpdesk_user"],
    "credit2": ["sales_team.group_sale_salesman_all_leads", "helpdesk.group_helpdesk_user"],
    "headoffice": ["sales_team.group_sale_manager", "helpdesk.group_helpdesk_manager", "hr.group_hr_user",
                   "account.group_account_invoice"],
    "ceo": ["sales_team.group_sale_salesman_all_leads", "helpdesk.group_helpdesk_user",
            "account.group_account_readonly"],
    "finance": ["account.group_account_invoice", "helpdesk.group_helpdesk_user"],
    "officer": ["sales_team.group_sale_salesman", "helpdesk.group_helpdesk_user"],
    "collections": ["helpdesk.group_helpdesk_user"],
    "auditor": ["account.group_account_readonly"],
}

# Employees: Roan Capital's eight positions (handbook), in departments.
# key (a sample staff account, or None), name, position, department, manager key, sex
EMPLOYEES = [
    ("ceo", "Daniel Mwaura", "Chief Executive Officer", "Management", None, "male"),
    ("headoffice", "Peter Kiprotich", "Head Office", "Management", "ceo", "male"),
    ("admin", "System Administrator", "Super Admin", "Operations", "headoffice", "other"),
    ("credit", "Grace Wanjiru", "Credit Manager", "Credit", "headoffice", "female"),
    ("credit2", "Mary Njeri", "Credit Manager", "Credit", "headoffice", "female"),
    ("officer", "Brian Otieno", "Loan Officer", "Credit", "credit", "male"),
    (None, "Mercy Chepkemoi", "Loan Officer", "Credit", "credit", "female"),
    (None, "Kevin Mutiso", "Loan Officer", "Credit", "credit2", "male"),
    ("finance", "Faith Achieng", "Finance / Cashier", "Finance", "headoffice", "female"),
    ("collections", "Janet Nyokabi", "Collections Officer", "Collections", "headoffice", "female"),
    (None, "Dennis Kiprop", "Collections Officer", "Collections", "collections", "male"),
    ("auditor", "Samuel Ruto", "Auditor", "Internal Audit", "ceo", "male"),
]
POSITIONS = {
    "Loan Officer": "Onboards clients, drafts and submits applications, house visits, follow-ups.",
    "Credit Manager": "Approves a loan's first stage; may originate.",
    "Head Office": "Approves the second stage.",
    "Chief Executive Officer": "Approves the third stage; write-offs and payment reversals.",
    "Finance / Cashier": "Prepares payouts; matches unidentified payments; the morning sign-off.",
    "Collections Officer": "Works the collection ladder: calls, visits, promises to pay, logged.",
    "Auditor": "Reads everything, the audit log included.",
    "Super Admin": "Creates and disables users; settings that move no money.",
}
DEPARTMENTS = ["Management", "Credit", "Finance", "Collections", "Operations", "Internal Audit"]

# CRM: loan enquiries. (name, phone, business, location, product, amount, source, outcome, days ago)
# outcome: new, qualified, proposition, won (an existing sample client), lost:<reason>
LEAD_SOURCES = ["Walk-in", "Phone call", "Referral by a client", "Field agent", "Facebook", "Request a Loan page"]
LOST_REASONS = ["Insufficient security", "Below the minimum business age", "Borrowed elsewhere",
                "Listed on a CRB", "Stopped responding"]
LEADS = [
    ("Esther Wangui", "0722418350", "Groceries", "Kangemi, Nairobi", "chattels", 15000, "Walk-in", "new", 1),
    ("Collins Kiprono", "0711290447", "Boda boda", "Kapsabet", "logbook", 60000, "Field agent", "new", 2),
    ("Faith Nduku", "0745501238", "Salon", "Machakos town", "chattels", 25000, "Facebook", "new", 0),
    ("Ibrahim Noor", "0790118842", "Hardware", "Garissa town", "title_deed", 100000, "Phone call", "qualified", 5),
    ("Lilian Akoth", "0728663017", "Fish vendor", "Kendu Bay", "chattels", 12000, "Referral by a client", "qualified", 7),
    ("Samuel Kirui", "0110274591", "Dairy farming", "Litein", "title_deed", 80000, "Request a Loan page", "proposition", 9),
    ("Ruth Wairimu", "0712770031", "Tailoring", "Nyahururu", "chattels", 18000, "Walk-in", "proposition", 4),
    ("Patrick Odera", "0733905562", "Matatu", "Kisumu", "logbook", 90000, "Phone call", "lost:Borrowed elsewhere", 20),
    ("Jane Muthoni", "0741662219", "Cereals", "Karatina", "chattels", 8000, "Walk-in", "lost:Insufficient security", 33),
    ("Hussein Ali", "0757330184", "Electronics", "Malindi", "chattels", 45000, "Facebook", "lost:Listed on a CRB", 26),
    ("Beatrice Chelangat", "0795014476", "Agrovet", "Kericho", "logbook", 70000, "Field agent", "lost:Stopped responding", 40),
]

# Helpdesk: complaints and queries (JN-08: acknowledged within 7 days, resolved within 30).
# (client index, subject, type, description, outcome, days ago, priority)
TICKET_TYPES = ["Complaint", "Query", "Request"]
TICKETS = [
    (2, "M-Pesa payment not showing on my loan", "Complaint",
     "Paid KES 1,000 via Paybill on Tuesday evening; the statement still shows arrears.", "solved", 12, "2"),
    (5, "Charged default interest after paying on time", "Complaint",
     "Says the instalment was paid before 6 pm on the due date but default interest was charged.", "in_progress", 6, "2"),
    (0, "Request for a loan statement", "Request",
     "Needs a statement of the last two loans for a bank account application.", "solved", 20, "0"),
    (9, "Collections officer called my employer", "Complaint",
     "Complains that a collector contacted someone other than the borrower and guarantor (reg 30).", "in_progress", 9, "3"),
    (13, "When will the logbook be released?", "Query",
     "Asks how long after the final payment the logbook is returned.", "solved", 30, "1"),
    (26, "Wrong amount disbursed", "Complaint",
     "Expected the full principal; received the amount after fees. Explain the deductions.", "solved", 8, "1"),
    (24, "Change of phone number", "Request",
     "Lost the old SIM; wants payments matched to a new number.", "new", 1, "1"),
    (15, "Asking for more time to pay", "Request",
     "Business affected by the floods; asks for a restructuring.", "new", 3, "2"),
    (12, "I never took this loan", "Complaint",
     "Caller says the loan was taken by a relative using her ID. Fraud check first.", "cancelled", 45, "3"),
]

# Accounting
# (name, what they bill, monthly amount before VAT, VAT applies)
VENDORS = [
    ("Westlands Office Park Ltd", "Office rent", 85000, True),
    ("Safaricom PLC", "Airtime, data and bulk SMS", 14500, True),
    ("Kenya Power and Lighting Co. PLC", "Electricity", 9800, True),
    ("Mwangi & Partners Advocates", "Chattels mortgage registration fees", 22000, False),
    ("Precise Valuers Ltd", "Vehicle and land valuations", 18000, True),
    ("Metro Credit Reference Bureau Ltd", "CRB checks", 4500, True),
    ("Rubis Energy Kenya Ltd", "Fuel for field visits", 16000, True),
]
