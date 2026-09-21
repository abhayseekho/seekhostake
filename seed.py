"""
seed.py — the reconciled pre-race WhatsApp book (18/7 chat, deduped latest-bet-per-person,
typos normalized). Full names resolved from Slack with Abhay (15 Sept):
Saya=Sai Godasala, Mitr=Vaibhav Rana, Tiwari=Abhay Tiwari, Rajat+Chawala=Rajat Chawla (one
person), Nishay=Nischay, Sarash=Saaransh (neither on Slack). Loaded once as admin-entered,
already-approved bets. Run: python seed.py  (or POST /api/admin/seed while the book is empty).
"""
SEED_BETS = [
    # name, amount ₹, side
    ("Yash Banwani",       5000, "khuseel"),
    ("Ashish Kumar",       5000, "khuseel"),
    ("Akash Deep",         5000, "khuseel"),
    ("Satya Iyengar",      5000, "khuseel"),
    ("Sai Godasala",       5000, "khuseel"),
    ("Naveed Pasha",       1000, "khuseel"),
    ("Manish Dangi",       1000, "khuseel"),
    ("Anuj Singh",          500, "khuseel"),
    ("Nischay",             500, "khuseel"),
    ("Saaransh",             50, "khuseel"),
    ("Shivam Maheshwari",  5000, "bansod"),
    ("Rajat Chawla",       5000, "bansod"),
    ("Vaibhav Rana",       5000, "bansod"),
    ("Abhay Tiwari",       5000, "bansod"),
    ("Prince",             5000, "bansod"),
    ("Abrar Khan",         5000, "bansod"),
    ("Vaibhav Varshney",   1000, "bansod"),
    ("Abhishek Dhiman",    1000, "bansod"),
]

if __name__ == "__main__":
    import store
    store.init()
    n = store.seed_bets(SEED_BETS)
    print(f"seeded {n} bets" if n else "book not empty — seed skipped")
