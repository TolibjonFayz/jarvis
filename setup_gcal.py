"""Google Calendar'ni FRIDAY'ga bir marta ulash.

Oldin: GCAL_SETUP.md bo'yicha data/google_client.json ni joylashtir.
Ishlatish: python setup_gcal.py  -> brauzer ochiladi, Google akkaunting bilan
kirib ruxsat berasan -> data/google_token.json saqlanadi. Keyin botni qayta ishga tushir.
"""
import os
import sys

import gcal


def main():
    if not os.path.exists(gcal.CLIENT_FILE):
        print(f"Topilmadi: {gcal.CLIENT_FILE}\nGCAL_SETUP.md dagi 1-4 qadamlarni bajar.")
        sys.exit(1)
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(gcal.CLIENT_FILE, gcal.SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", open_browser=True)
    with open(gcal.TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    print("Tayyor! Token saqlandi:", gcal.TOKEN_FILE)
    print("Tekshiruv:", gcal.events_text("hafta").splitlines()[0])
    print("Endi botni qayta ishga tushir (yoki Claude'ga ayt).")


if __name__ == "__main__":
    main()
