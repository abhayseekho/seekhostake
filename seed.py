"""
seed.py — the reconciled pre-race WhatsApp book (18/7 chat, deduped latest-bet-per-person,
typos normalized; Satya and Saya confirmed as different people). Loaded once as admin-entered,
already-approved bets. Run: python seed.py  (or POST /api/admin/seed while the book is empty).
"""
SEED_BETS = [
    # name, amount ₹, side
    ("Yash",     5000, "khuseel"),
    ("Ashish",   5000, "khuseel"),
    ("Akash",    5000, "khuseel"),
    ("Satya",    5000, "khuseel"),
    ("Saya",     5000, "khuseel"),
    ("Naveed",   1000, "khuseel"),
    ("Manish",   1000, "khuseel"),
    ("Anuj",      500, "khuseel"),
    ("Nishay",    500, "khuseel"),
    ("Sarash",     50, "khuseel"),
    ("Shivam",   5000, "bansod"),
    ("Rajat",    5000, "bansod"),
    ("Mitr",     5000, "bansod"),
    ("Tiwari",   5000, "bansod"),
    ("Chawala",  5000, "bansod"),
    ("Prince",   5000, "bansod"),
    ("Abrar",    5000, "bansod"),
    ("Varshney", 1000, "bansod"),
    ("Dhiman",   1000, "bansod"),
]

if __name__ == "__main__":
    import store
    store.init()
    n = store.seed_bets(SEED_BETS)
    print(f"seeded {n} bets" if n else "book not empty — seed skipped")
