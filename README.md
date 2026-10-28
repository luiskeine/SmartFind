# SmartFind — Campus Lost & Found

SmartFind is a Streamlit browser app for submitting lost/found reports and ranking possible matches. During Step 1, each user can choose V1 (`models/best.pt`) or V2 (`models/best_v2.pt`) for photo detection; the choice is private to their session. The selected YOLO model detects supported item categories and returns a bounding box; the app analyzes that crop for a color estimate and optional OCR text. Detected brand candidates are preselected in the report form, and users can change suggestions before saving.

## Run locally

Use Python 3.10–3.12. Install the Python packages, then start the Streamlit server:

```powershell
python -m pip install -r requirements.txt
streamlit run main.py
```

Open the local URL printed by Streamlit (normally `http://localhost:8501`) in a browser. Keep both `models/best.pt` (V1, loaded with Ultralytics) and `models/best_v2.pt` (V2, the YOLOv5 checkpoint loaded with the `yolov5` runtime) in place. The `setuptools<81` pin keeps `pkg_resources` available for YOLOv5 7.0.14. V2 loads this trusted checkpoint with PyTorch's restricted unpickler and a narrow allowlist of the model classes it uses. Each signed-in user can select their detector in the report's Step 1; the choice is private to that Streamlit session and does not affect other users. Set `SMARTFIND_MODEL_PATH` or `SMARTFIND_MODEL_V2_PATH` to override either checkpoint. `SMARTFIND_DETECTION_CONFIDENCE` optionally changes the detector threshold for both (default `0.40`; tune against representative campus photos).

## Sign-in and roles

SmartFind supports Google OIDC sign-in and anonymous guest accounts. Verified emails in `student_email_domains` receive the `student` role, and verified addresses explicitly listed in `admin_emails` receive the `admin` role. Students and guests can submit reports, see found reports and their own lost reports, and receive in-app match notifications; admins can manage all records. Guest accounts cannot access admin features and do not receive email notifications.

Choose **Continue as guest** to create a persistent guest account. SmartFind generates a high-entropy recovery code; save it privately because it is shown only once and is required to resume that account on another visit or device. The database stores a digest of the code, not the code itself. Anyone with the recovery code can access that guest account, and a lost code cannot be recovered. Guest data remains in the database until an administrator deletes it from Supabase. A configured Supabase database is still required. Google sign-in and its `[auth]` settings remain necessary for verified student/admin accounts; they are optional for guests.

## Reports, drafts, and appearance

Report submission uses a three-step flow: add an optional photo, enter and save private details, then review and explicitly submit. Incomplete drafts are stored in Supabase under the signed-in email or guest account and can be resumed on another device by signing in or using the guest recovery code. A draft is not visible as a report and does not participate in matching until submitted. Each account can keep one draft for each report type; deleting a draft removes it permanently. Use **My Reports** to review, update, resolve, delete, or transfer custody for reports submitted by the current account. Database data reloads at initial sign-in/account change and when entering **Lost & Found Records**, **Possible Matches**, or **Notifications**; use the Refresh data control inside those three pages to synchronize again. Ordinary navigation and form/widget reruns do not reload the database.

Use **Dark theme** in the sidebar to switch appearance. Both themes explicitly style text, fields, primary/secondary/disabled buttons, navigation, and custom surfaces; declared foreground/background pairs are tested against WCAG AA contrast. Theme and Records search/filter preferences are saved to the account and restored across devices. The app uses brief interaction transitions and honors the device's reduced-motion preference. The layout adapts to phone, tablet, and desktop sizes; controls are sized for touch use.

Create `.streamlit/secrets.toml` for local use. This file is git-ignored; never commit real credentials. Register both the local and deployed callback URLs in the Google OAuth client. In Streamlit Community Cloud, paste the same settings into the app's **Secrets** settings, changing `redirect_uri` to the deployed URL:

```toml
[auth]
redirect_uri = "http://localhost:8501/oauth2callback"
cookie_secret = "replace-with-a-long-random-secret"
client_id = "your-google-oauth-client-id"
client_secret = "your-google-oauth-client-secret"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"

[smartfind]
student_email_domains = ["tip.edu.ph"]
admin_emails = ["your-admin-account@tip.edu.ph"]

[mail]
smtp_host = "smtp.gmail.com"
smtp_port = 587
smtp_username = "your-sender@gmail.com"
smtp_password = "your-google-app-password"
from_email = "your-sender@gmail.com"
app_url = "https://<your-app-subdomain>.streamlit.app"
```

For the hosted app, set `redirect_uri` to `https://<your-app-subdomain>.streamlit.app/oauth2callback` and add that exact callback URL to the Google OAuth client's authorized redirect URIs. Add every authorized admin's exact email to `admin_emails`. If your campus uses another identity provider/domain, configure its OIDC metadata URL and email domain instead. Without OIDC settings, verified-account sign-in is unavailable, but guests can still use the app when Supabase is configured.

## Supabase database

SmartFind uses Supabase PostgreSQL. Add this to Streamlit Cloud **Secrets** (or local `.streamlit/secrets.toml`):

```toml
[supabase]
database_url = "postgresql://postgres.<project-ref>:<encoded-password>@<session-pooler-host>:5432/postgres"
```

Get the URI from the Supabase project's **Connect → Direct → Session pooler** panel. Use the actual host, username, project reference, and database name shown there; encode special characters in the database password. Keep the URI secret. SmartFind connects from the Python server using SSL and creates its PostgreSQL tables automatically on first use; no SQL Editor setup is needed. Keep the Supabase Data API and automatic table exposure disabled for this server-side connection. The app enables RLS on its tables as additional protection.

### Supabase Data API log noise

With the Data API disabled, Supabase's PostgREST service can repeatedly log `schema "pg_pgrst_no_exposed_schemas" does not exist` (`3F000`). This is a known Supabase issue and does not come from SmartFind queries or change the direct PostgreSQL connection's access rules. If the entries are distracting, use the [official workaround](https://supabase.com/docs/guides/troubleshooting/schema-pg_pgrst_no_exposed_schemas-does-not-exist) in the project's SQL Editor; it exposes only an empty schema to PostgREST while leaving the Data API disabled for SmartFind.

`database_url` is required. Reports and notification data are stored only in Supabase; uploaded photo thumbnails remain embedded in report JSON. For larger-scale use, move them to a private Supabase Storage bucket. Supabase Free currently includes 500 MB of database storage and can pause a project after a week of inactivity; check the [current plan limits](https://supabase.com/pricing).

### Gmail notifications

Email is optional. To send match alerts from Gmail, configure the `[mail]` section above in Streamlit Cloud **Secrets** (or local `.streamlit/secrets.toml`). Use a Google **App Password**, not your normal Gmail password. App Passwords require 2-Step Verification and may be disabled by a Google Workspace administrator. In Google Account settings, create an App Password for SmartFind and place it in `smtp_password`; never commit or share it. The sender uses Gmail SMTP with STARTTLS on port `587`.

Each strong match produces an inbox item for both report owners. When SMTP is configured, pending messages are sent once and their status is saved as sent/failed. An admin can use **Test Gmail connection** on Admin Management to check connect, STARTTLS, authentication, and SMTP response without sending a message. If it fails, the error names the SMTP stage. If Cloud cannot connect or complete TLS, its network may block outbound SMTP; use an HTTPS email API provider instead of repeatedly changing the Gmail password. If authentication fails, verify the App Password belongs to `smtp_username`. If a process stops mid-send, an attempt left in `sending` for more than two minutes is marked failed on the next app run. Check inbox/spam before retrying an interrupted attempt because Gmail may already have accepted it. Other failed messages can be retried from that owner's Notifications page. If mail is not configured, the in-app notice still works and the email status says `Email not configured`. Older inbox notices from before email support are marked legacy and are not sent retroactively.

### OCR setup

The app uses RapidOCR with ONNX Runtime as its primary OCR engine; install it with `requirements.txt`. It does not require a separate Tesseract executable. Tesseract remains an optional fallback if RapidOCR is unavailable. OCR reads visible text, not logos, and brand candidates must be confirmed by the user.

## Browser deployment

The included `Dockerfile` builds a browser-accessible container. Build and run it with Docker, publishing port `8501`. For Streamlit Community Cloud, deploy `main.py`, retain both `models/best.pt` and `models/best_v2.pt` in the repository, and configure the Supabase secret.

## How suggestions and matches work

1. A user selects V1 or V2 and uploads or takes a photo in Step 1 of the lost/found form.
2. If YOLO detects an item, the detected crop is analyzed. If it returns no box, SmartFind still runs OCR on the full photo and estimates color from its center region; the category must then be selected manually.
3. RapidOCR reads text and matches it to canonical brand labels, including configured legal-name aliases. The brand form is a category-specific list with OCR candidates, an Unknown choice, and a manual Other option. Color is a rough pixel estimate.
4. Confirmed category, color, canonical brand, date, location, description, owner identity, and photo thumbnail are saved in Supabase PostgreSQL.
5. The matching agent compares open Lost and Found reports. Location matching recognizes matching room codes or campus areas inside longer text, plus exact shared keywords and conservative close keyword spellings for partial points. Brand shares the existing 10-point description allocation when either report supplies a brand (5 points each); otherwise legacy scoring is unchanged. Strong possible matches create persistent, per-owner inbox notifications; each owner can mark them read. When SMTP is configured, one email is sent to each owner. Scores are rule-based similarity, not probabilities or proof of ownership.

YOLO category detection is not instance-level image matching: two objects of the same category are not visually proven to be the same object. The V1 and V2 checkpoints are selected per signed-in Streamlit session. Their labels are normalized into one shared category vocabulary (for example, `Smartphone` and `Mobile phone` both become `Mobile phone`) so reports from different model versions can still match. Category choices include the combined 24 labels; a given model can only detect classes it was trained to recognize. Color estimation is a basic pixel heuristic and can be affected by lighting/backgrounds; in no-detection fallback it samples the image center. OCR may miss stylized text and does not recognize logo graphics. With no detected category, OCR checks the whole photo against the combined brand shortlist, which may increase false positives; the user must confirm any suggested brand.

## Found-item custody and handoff demo

Each found report begins with **Finder** as the current holder. The student/person who submitted the report, or an authorized admin, can transfer custody to **OSA** after handing the item to the Office of Student Affairs. The control is available from the report details; admins can also update it in **Admin Management**.

Every successful custody change adds to a short history showing the new holder, the account that made the change, and the timestamp. Returning custody to **Finder** is also allowed. Custody does not affect matching scores or notifications: it is a current-location/status aid for the lost-and-found process, not proof that a report belongs to a specific person.

For a five-minute demonstration:

1. Submit a Found report as a guest or signed-in student.
2. Open **Lost & Found Records**, select the report, and confirm that it is held by **Finder**.
3. Open the details and change **Current holder** to **OSA**.
4. Show the updated Records/details label and the custody-history entry.
5. If desired, demonstrate an authorized admin changing the holder back to **Finder** and explaining that only the report owner or admin can make this update.

## Data, tests, and current limitations

- Supabase projects start empty; there are no local demo records or SQLite migration path.
- Run the pure-logic and storage/vision tests with `python -m unittest -v`.
- Notifications persist in each owner's inbox; SMTP email requires Gmail credentials in Streamlit Secrets.
- Use authentic photos from the supported classes to evaluate model accuracy and tune the confidence threshold before operational use.
- Public production use still needs reviewed privacy/retention policies, durable managed storage, backups, and an operational admin process. OIDC identity and role checks are implemented, but must be configured correctly before opening access.
