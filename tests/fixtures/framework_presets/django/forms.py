"""Django ModelForm fixtures - ``fields = "__all__"`` is the SAFE906 trigger."""


class ItemForm:
    class Meta:
        model = "Item"
        fields = "__all__"  # SAFE906: binds every model field


class SafeItemForm:
    class Meta:
        model = "Item"
        fields = ["name", "price"]  # negative control: explicit allow-list
