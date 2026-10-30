# Standard GSM 7-bit basic character set
GSM_BASIC_CHARS = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ\x1bÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)

# GSM 7-bit extension characters (count as 2 characters in GSM encoding)
GSM_EXTENSION_CHARS = set("^{}\\[~]|€")


def calculate_sms_segments(text: str) -> dict:
    """
    Computes exact segment count and character metrics based on standard telecom GSM/Unicode rules.
    """
    if not text:
        return {
            'is_unicode': False,
            'character_count': 0,
            'segment_count': 0,
            'chars_remaining_in_segment': 160,
            'max_chars_in_current_segment': 160
        }

    # Determine if text contains non-GSM characters
    is_unicode = False
    gsm_char_count = 0

    for ch in text:
        if ch in GSM_BASIC_CHARS:
            gsm_char_count += 1
        elif ch in GSM_EXTENSION_CHARS:
            gsm_char_count += 2
        else:
            is_unicode = True
            break

    if is_unicode:
        # Unicode (UCS-2) encoding
        char_count = len(text)
        if char_count <= 70:
            segment_count = 1
            max_chars = 70
            chars_remaining = 70 - char_count
        else:
            segment_count = (char_count + 66) // 67
            max_chars = segment_count * 67
            chars_remaining = max_chars - char_count
    else:
        # GSM 7-bit encoding
        char_count = gsm_char_count
        if char_count <= 160:
            segment_count = 1
            max_chars = 160
            chars_remaining = 160 - char_count
        else:
            segment_count = (char_count + 152) // 153
            max_chars = segment_count * 153
            chars_remaining = max_chars - char_count

    return {
        'is_unicode': is_unicode,
        'character_count': char_count,
        'segment_count': max(1, segment_count),
        'chars_remaining_in_segment': max(0, chars_remaining),
        'max_chars_in_current_segment': max_chars
    }
