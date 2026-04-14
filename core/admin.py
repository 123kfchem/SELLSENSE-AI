from django.contrib import admin
from .models import Item, ItemReport, Sale, UserProfile

admin.site.register(UserProfile)
admin.site.register(Item)
admin.site.register(Sale)
admin.site.register(ItemReport)
