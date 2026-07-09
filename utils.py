import re

EMAIL_PATTERN = re.compile(
    r"^(?=.{1,254}$)"  # Entire email <= 254 chars
    r"(?=.{1,64}@)"  # Local part <= 64 chars
    r"[A-Za-z0-9](?:[A-Za-z0-9._%+-]{0,62}[A-Za-z0-9])?"
    r"@"
    r"(?:[A-Za-z0-9-]+\.)+"
    r"[A-Za-z]{2,63}$"
)


def validate_email(email: str):
    email = email.strip()

    if not EMAIL_PATTERN.fullmatch(email):
        return {"valid": False, "username": None}

    username = email.split("@", 1)[0]

    return {"valid": True, "username": username.strip().lower()}


if __name__ == "__main__":
    emails = [
        "barasapeter52@gmail.com",
        "john.doe@example.co.uk",
        "user_name123@sub.domain.org",
        "my-email+work@company.io",
        "a@b.co",
        "invalid@email",
        "@gmail.com",
        "hello@@gmail.com",
        ".john@gmail.com",
        "john.@gmail.com",
    ]

    for email in emails:
        result = validate_email(email)

        print(f"Email: {email}")
        print(f"Valid: {'YES' if result['valid'] else 'NO'}")

        if result["valid"]:
            print(f"Username: {result['username']}")

        print("-" * 40)
