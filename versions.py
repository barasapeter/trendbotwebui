from importlib.metadata import version, PackageNotFoundError

packages = [
    "fastapi",
    "requests",
    "websockets",
    "python-dotenv",  # pip package name
    "uvicorn",
    "jinja2",
    "tzdata",
    "itsdangerous",
]

print("Installed package versions:\n")

for package in packages:
    try:
        print(f"{package:<15} {version(package)}")
    except PackageNotFoundError:
        print(f"{package:<15} Not installed")
