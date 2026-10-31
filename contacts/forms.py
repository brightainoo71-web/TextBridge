from django import forms
from .models import Contact, ContactGroup, SuppressionRecord, BirthdayAutomation
from .utils import normalize_phone_number


class ContactForm(forms.ModelForm):
    group = forms.ModelChoiceField(
        queryset=None,
        required=False,
        empty_label="-- No Group (Unassigned) --",
        help_text="Optionally assign to a contact group"
    )

    class Meta:
        model = Contact
        fields = ['name', 'phone_number', 'email', 'birth_date', 'is_subscribed']
        widgets = {
            'birth_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        business = kwargs.pop('business', None)
        super().__init__(*args, **kwargs)
        if business:
            self.fields['group'].queryset = ContactGroup.objects.filter(business=business)

    def clean_phone_number(self):
        raw_phone = self.cleaned_data.get('phone_number')
        is_valid, normalized, err = normalize_phone_number(raw_phone)
        if not is_valid:
            raise forms.ValidationError(err)
        return normalized


class ContactGroupForm(forms.ModelForm):
    class Meta:
        model = ContactGroup
        fields = ['name', 'description']


class ContactImportForm(forms.Form):
    file = forms.FileField(
        label="Select CSV or Excel (.xlsx) file",
        help_text="Max 10MB. File should contain at least Name and Phone columns."
    )
    group = forms.ModelChoiceField(
        queryset=None,
        required=False,
        empty_label="-- Do Not Assign to a Group --",
        help_text="Optional target contact group for all imported contacts"
    )
    duplicate_policy = forms.ChoiceField(
        choices=[
            ('SKIP', 'Skip duplicate phone numbers (preserve existing contact details)'),
            ('UPDATE', 'Update existing contacts with newly imported name and email')
        ],
        initial='SKIP',
        label="Duplicate Handling Policy"
    )

    def __init__(self, *args, **kwargs):
        business = kwargs.pop('business', None)
        super().__init__(*args, **kwargs)
        if business:
            self.fields['group'].queryset = ContactGroup.objects.filter(business=business)

    def clean_file(self):
        uploaded_file = self.cleaned_data.get('file')
        if uploaded_file:
            name = uploaded_file.name.lower()
            if not (name.endswith('.csv') or name.endswith('.xlsx')):
                raise forms.ValidationError("Only .csv or .xlsx spreadsheets are supported.")
            if uploaded_file.size > 10 * 1024 * 1024:
                raise forms.ValidationError("File size exceeds 10MB limit.")
        return uploaded_file


class SuppressionForm(forms.ModelForm):
    class Meta:
        model = SuppressionRecord
        fields = ['phone_number', 'reason', 'notes']

    def clean_phone_number(self):
        raw_phone = self.cleaned_data.get('phone_number')
        is_valid, normalized, err = normalize_phone_number(raw_phone)
        if not is_valid:
            raise forms.ValidationError(err)
        return normalized


class BirthdayAutomationForm(forms.ModelForm):
    sender_id = forms.ChoiceField(choices=[], label="Sender ID", help_text="Sender header for birthday SMS")

    class Meta:
        model = BirthdayAutomation
        fields = ['is_enabled', 'sender_id', 'dispatch_time', 'message_template']
        widgets = {
            'dispatch_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'message_template': forms.Textarea(attrs={
                'class': 'form-control font-mono',
                'rows': 4,
                'placeholder': 'Happy Birthday {{first_name}}! 🎉...'
            }),
        }

    def __init__(self, *args, **kwargs):
        business = kwargs.pop('business', None)
        super().__init__(*args, **kwargs)
        if business:
            from messaging.models import SenderID
            custom_sids = list(SenderID.objects.filter(business=business, status=SenderID.Status.APPROVED))
            system_sids = list(SenderID.objects.filter(is_system_default=True, status=SenderID.Status.APPROVED))
            choices = []
            for s in custom_sids:
                choices.append((s.sender_id, f"{s.sender_id} (Your Verified Brand)"))
            for s in system_sids:
                choices.append((s.sender_id, f"{s.sender_id} (Platform Default - Instant)"))
            if not choices:
                fallback = (business.preferred_sender_id or business.name[:11].replace(' ', '')).upper()
                choices = [(fallback, f"{fallback} (Default)")]
            posted_sid = self.data.get('sender_id')
            if posted_sid and not any(posted_sid == c[0] for c in choices):
                choices.insert(0, (posted_sid, posted_sid))
            self.fields['sender_id'].choices = choices
