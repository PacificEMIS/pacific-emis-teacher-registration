"""
Utility functions for teacher registration.

This module contains helper functions for generating teacher registration numbers
and other registration-related utilities.
"""

import hashlib
from django.conf import settings
from django.core.exceptions import ValidationError


def base36_encode(number):
    """
    Encode a number in base36 (0-9, A-Z).

    Args:
        number: Integer to encode

    Returns:
        str: Base36 encoded string
    """
    if number == 0:
        return '0'

    alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    base36 = ''

    while number:
        number, remainder = divmod(number, 36)
        base36 = alphabet[remainder] + base36

    return base36


def calculate_check_digit(value):
    """
    Calculate check digit using Luhn-like algorithm.

    Args:
        value: String value to calculate check digit for

    Returns:
        str: Single character check digit (0-9 or A-Z)
    """
    # Convert alphanumeric to numbers
    alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    digit_sum = 0

    for i, char in enumerate(reversed(value.upper())):
        if char in alphabet:
            num = alphabet.index(char)
            # Double every second digit
            if i % 2 == 1:
                num *= 2
                # If result is two digits, add them together
                if num > 35:
                    num = (num // 36) + (num % 36)
            digit_sum += num

    # Check digit is what makes sum divisible by 36
    check = (36 - (digit_sum % 36)) % 36
    return alphabet[check]


def generate_teacher_registration_number(national_id, date_of_birth, approval_year):
    """
    Generate deterministic teacher registration number.

    Format: TR{YY}-{HASH}-{CHECK}
    Example: TR26-A7K9-C

    Components:
    - TR: Teacher Registration prefix
    - YY: Year of approval (2-digit)
    - HASH: Base36-encoded SHA256 hash of (National ID + DOB + SECRET_KEY)
    - CHECK: Check digit for error detection

    Properties:
    - Deterministic: Same National ID + DOB + Year → Same number (unless SECRET_KEY changes)
    - Unique: Hash-based, ~1.6M combinations per year
    - One-time generation: Created on approval, stored permanently in database
    - Stable: Based on verified National ID document
    - Uses Django SECRET_KEY as salt (simpler, already secret and unique per installation)

    Edge Cases:
    - Generated once and stored in SchoolStaff.teacher_registration_number
    - Never auto-regenerated (even if National ID or DOB corrected)
    - Can be manually regenerated via admin tool if needed
    - Collision prevention: Duplicate National ID check before approval

    Args:
        national_id: National ID/Passport number (normalized)
        date_of_birth: Date of birth (for uniqueness, can have errors)
        approval_year: Year of registration approval (contextual)

    Returns:
        str: Registration number in format TR{YY}-{HASH}-{CHECK}

    Raises:
        ValidationError: If inputs missing or invalid
    """
    # Validate inputs
    if not national_id or not national_id.strip():
        raise ValidationError("National ID is required for registration number generation")

    if not date_of_birth:
        raise ValidationError("Date of birth is required for registration number generation")

    if not approval_year:
        raise ValidationError("Approval year is required for registration number generation")

    # Normalize inputs
    national_id_normalized = national_id.strip().upper()
    dob_str = date_of_birth.isoformat()  # YYYY-MM-DD format

    # Use Django's SECRET_KEY as salt (simpler, already secret and unique)
    salt = settings.SECRET_KEY

    # Create hash input: National ID | DOB | Salt
    hash_input = f"{national_id_normalized}|{dob_str}|{salt}"

    # Generate SHA256 hash
    hash_digest = hashlib.sha256(hash_input.encode('utf-8')).digest()

    # Take first 4 bytes (32 bits), convert to integer
    hash_value = int.from_bytes(hash_digest[:4], byteorder='big')

    # Encode in base36 and pad to 4 characters
    hash_b36 = base36_encode(hash_value).zfill(4).upper()

    # Get 2-digit year
    year_short = str(approval_year)[-2:]

    # Calculate check digit on year + hash
    check_digit = calculate_check_digit(f"{year_short}{hash_b36}")

    # Format: TR26-A7K9-C
    registration_number = f"TR{year_short}-{hash_b36}-{check_digit}"

    return registration_number


def validate_registration_number(registration_number):
    """
    Validate a teacher registration number format and check digit.

    Args:
        registration_number: Registration number to validate (e.g., "TR26-A7K9-C")

    Returns:
        bool: True if valid, False otherwise
    """
    if not registration_number:
        return False

    # Expected format: TR{YY}-{HASH}-{CHECK}
    # Example: TR26-A7K9-C (length: 12)
    if len(registration_number) != 12:
        return False

    if not registration_number.startswith('TR'):
        return False

    parts = registration_number[2:].split('-')
    if len(parts) != 3:
        return False

    year_part, hash_part, check_part = parts

    # Validate lengths
    if len(year_part) != 2 or len(hash_part) != 4 or len(check_part) != 1:
        return False

    # Validate check digit
    expected_check = calculate_check_digit(f"{year_part}{hash_part}")

    return check_part.upper() == expected_check.upper()
