from django import forms
from django.utils import timezone
from contacts.models import ContactGroup
from contacts.utils import normalize_phone_number
from .models import SMSCampaign, SenderID, SMSMessage


class SenderIDForm(forms.ModelForm):
    class Meta:
        model = SenderID
        fields = ['sender_id', 'purpose']

    def clean_sender_id(self):
        sid = self.cleaned_data.get('sender_id', '').strip()
        if not sid.isalnum():
            raise forms.ValidationError("Sender ID can only contain letters and numbers (no spaces or special symbols).")
        if len(sid) > 11:
            raise forms.ValidationError("Sender ID maximum length is 11 characters.")
        if len(sid) < 3:
            raise forms.ValidationError("Sender ID must be at least 3 characters.")
        return sid.upper()


class CampaignComposeForm(forms.ModelForm):
    sender_id = forms.ChoiceField(choices=[], label="Sender ID", help_text="Select your verified Sender ID")
    target_group = forms.ModelChoiceField(
        queryset=None,
        required=False,
        empty_label="All Contacts (Entire Business Contact List)",
        label="Target Recipients"
    )
    scheduled_at = forms.DateTimeField(
        required=False,
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'],
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control form-control-sm'}),
        label="Scheduled Time"
    )

    class Meta:
        model = SMSCampaign
        fields = ['title', 'sender_id', 'target_group', 'message_template', 'is_scheduled', 'scheduled_at']
        widgets = {
            'message_template': forms.Textarea(attrs={
                'rows': 5,
                'placeholder': 'Type your message here... Use {{name}} to personalize with contact full name.',
                'id': 'message_template'
            }),
        }

    def clean(self):
        cleaned_data = super().clean()
        is_scheduled = cleaned_data.get('is_scheduled')
        scheduled_at = cleaned_data.get('scheduled_at')

        if is_scheduled:
            if not scheduled_at:
                self.add_error('scheduled_at', "Please specify a future date and time for the scheduled broadcast.")
            elif scheduled_at <= timezone.now():
                self.add_error('scheduled_at', "Scheduled broadcast time must be set in the future.")
        else:
            cleaned_data['scheduled_at'] = None

        return cleaned_data

    def __init__(self, *args, **kwargs):
        business = kwargs.pop('business', None)
        super().__init__(*args, **kwargs)
        if business:
            self.fields['target_group'].queryset = ContactGroup.objects.filter(business=business)
            
            # 1. Custom verified sender IDs for this business
            custom_sids = list(SenderID.objects.filter(business=business, status=SenderID.Status.APPROVED))
            # 2. Platform-wide verified system default sender IDs
            system_sids = list(SenderID.objects.filter(is_system_default=True, status=SenderID.Status.APPROVED))
            
            choices = []
            for s in custom_sids:
                choices.append((s.sender_id, f"{s.sender_id} (Your Verified Brand)"))
            for s in system_sids:
                choices.append((s.sender_id, f"{s.sender_id} (Platform Default - Instant)"))

            if not choices:
                fallback = (business.preferred_sender_id or business.name[:11].replace(' ', '')).upper()
                choices = [(fallback, f"{fallback} (Default)")]
            
            self.fields['sender_id'].choices = choices


class SingleMessageForm(forms.Form):
    sender_id = forms.ChoiceField(choices=[], label="Sender ID")
    recipient_phone = forms.CharField(max_length=25, label="Recipient Phone (e.g. 024XXXXXXX or 23324XXXXXXX)")
    message = forms.CharField(widget=forms.Textarea(attrs={'rows': 4}), label="Message Text")

    def __init__(self, *args, **kwargs):
        business = kwargs.pop('business', None)
        super().__init__(*args, **kwargs)
        if business:
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
            self.fields['sender_id'].choices = choices

    def clean_recipient_phone(self):
        raw = self.cleaned_data.get('recipient_phone')
        is_valid, norm, err = normalize_phone_number(raw)
        if not is_valid:
            raise forms.ValidationError(err)
        return norm
