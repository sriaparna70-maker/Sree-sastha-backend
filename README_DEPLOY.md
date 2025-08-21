# Backend (Flask) for Render/Railway
Deploy this to Render (recommended) so you don't type export each time.
1) Create a new Web Service from this folder.
2) Set env vars in the dashboard:
   - ZOHO_EMAIL = sivaramanganesan@zohomail.in
   - ZOHO_APP_PASSWORD = <your 16-char Zoho app password>
   - ZOHO_TO_EMAIL = sivaramanganesan@zohomail.in
   - ZOHO_SMTP_HOST = smtp.zoho.in
   - FRONTEND_ORIGIN = https://<your-username>.github.io  (set after Pages is live)
3) On first deploy, the DB (leads.db) is auto-initialised.
4) Your API will be at: https://<service-name>.onrender.com/api/contact
