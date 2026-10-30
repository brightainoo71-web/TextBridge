import re

# Recognized Ghanaian Network 2-digit prefixes following country code 233
# MTN: 24, 54, 55, 59, 53
# Telecel (Vodafone): 20, 50
# AT (AirtelTigo): 27, 57, 26, 56
# Glo: 23
GHANA_VALID_PREFIXES = {
    '24', '54', '55', '59', '53',
    '20', '50',
    '27', '57', '26', '56',
    '23'
}


def normalize_phone_number(raw_phone: str, default_country: str = 'GH') -> tuple[bool, str, str]:
    """
    Validates and normalizes phone numbers into E.164 international format without leading '+'.
    For Ghana (GH): produces 12-digit number e.g. 233241234567.

    Returns:
        (is_valid: bool, normalized_number: str, error_message: str)
    """
    if not raw_phone:
        return False, '', "Phone number is empty"

    # Remove all spaces, dashes, dots, parentheses
    cleaned = re.sub(r'[\s\-\(\)\.]+', '', str(raw_phone).strip())

    if not cleaned:
        return False, '', "Phone number contains no digits"

    # Handle leading '+'
    if cleaned.startswith('+'):
        cleaned = cleaned[1:]

    # Handle international '00' prefix
    if cleaned.startswith('00'):
        cleaned = cleaned[2:]

    # Keep only digits
    if not cleaned.isdigit():
        return False, '', "Phone number contains invalid non-numeric characters"

    # Check Ghanaian local format: 10 digits starting with '0' e.g. 0241234567
    if len(cleaned) == 10 and cleaned.startswith('0'):
        # Convert local 0XX to international 233XX
        prefix = cleaned[1:3]
        if prefix in GHANA_VALID_PREFIXES:
            normalized = '233' + cleaned[1:]
            return True, normalized, ""
        else:
            return False, '', f"Invalid Ghanaian network prefix '0{prefix}'"

    # Check Ghanaian format starting with 233
    if cleaned.startswith('233'):
        if len(cleaned) == 12:
            prefix = cleaned[3:5]
            if prefix in GHANA_VALID_PREFIXES:
                return True, cleaned, ""
            else:
                return False, '', f"Invalid Ghanaian network prefix '{prefix}'"
        else:
            return False, '', f"Ghanaian phone number must have 12 digits (found {len(cleaned)})"

    # Check other international numbers (min 9 digits, max 15 digits per E.164)
    if 9 <= len(cleaned) <= 15:
        return True, cleaned, ""

    return False, '', f"Phone number length {len(cleaned)} is out of valid range (9-15 digits)"
