from importlib.metadata import version, PackageNotFoundError

# (display name, actual package name)
packages = [
    ("fastapi", "fastapi"),
    ("uvicorn[standard]", "uvicorn"),
    ("websockets", "websockets"),
    ("requests", "requests"),
    ("python-dotenv", "python-dotenv"),
    ("pydantic", "pydantic"),
]

print("# requirements.txt")
print()

for display_name, package_name in packages:
    try:
        print(f"{display_name}=={version(package_name)}")
    except PackageNotFoundError:
        print(f"# {display_name} is not installed")
