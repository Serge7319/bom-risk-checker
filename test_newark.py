from integrations.newark_client import search_newark_by_part_number

test_parts = [
    "LM555CN",
    "LM358N",
    "NE555P",
    "LM7805CT",
    "1N4148",
]

for part in test_parts:
    print("\n======================")
    print(f"Testing: {part}")

    try:
        result = search_newark_by_part_number(part)
        print(result)
    except Exception as e:
        print(f"ERROR: {e}")