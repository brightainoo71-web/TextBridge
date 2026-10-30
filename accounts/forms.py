from django import forms
from django.contrib.auth.forms import AuthenticationForm
from .models import User, Business, BusinessMembership
from contacts.utils import normalize_phone_number


class RegistrationForm(forms.ModelForm):
    business_name = forms.CharField(max_length=255, label="Business or Organization Name")
    business_category = forms.ChoiceField(choices=Business.Category.choices, label="Business Category")
    preferred_sender_id = forms.CharField(
        max_length=11,
        required=False,
        label="Preferred Sender ID (Max 11 characters)",
        help_text="e.g., POWERGYM, KINGSCHOOL, SHOPRITE"
    )
    password = forms.CharField(widget=forms.PasswordInput, min_length=8, label="Password")
    password_confirm = forms.CharField(widget=forms.PasswordInput, label="Confirm Password")

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone_number']

    def clean_preferred_sender_id(self):
        sid = self.cleaned_data.get('preferred_sender_id', '').strip()
        if sid:
            if not sid.isalnum():
                raise forms.ValidationError("Sender ID can only contain alphanumeric characters (no spaces or symbols).")
            if len(sid) > 11:
                raise forms.ValidationError("Sender ID cannot exceed 11 characters.")
        return sid.upper()

    def clean_phone_number(self):
        phone = self.cleaned_data.get('phone_number')
        if phone:
            is_valid, norm_phone, err = normalize_phone_number(phone)
            if not is_valid:
                raise forms.ValidationError(err)
            return norm_phone
        return phone

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get('password')
        p2 = cleaned_data.get('password_confirm')
        if p1 and p2 and p1 != p2:
            self.add_error('password_confirm', "Passwords do not match.")
        return cleaned_data


class BusinessProfileForm(forms.ModelForm):
    class Meta:
        model = Business
        fields = ['name', 'category', 'contact_email', 'contact_phone', 'address', 'city', 'preferred_sender_id']

    def clean_preferred_sender_id(self):
        sid = self.cleaned_data.get('preferred_sender_id', '').strip()
        if sid:
            if not sid.isalnum():
                raise forms.ValidationError("Sender ID must be alphanumeric.")
            if len(sid) > 11:
                raise forms.ValidationError("Sender ID cannot exceed 11 characters.")
        return sid.upper()
