# Play Store release kit: Smart Bus

Everything needed to publish `in.smartbus.app` on Google Play.

## Files

| File | Use in Play Console |
|---|---|
| `mobile/android/app/build/outputs/bundle/release/app-release.aab` (build output, not in git) | **Release → Production / Internal testing → Upload** |
| `icon-512.png` | Store listing → App icon (512×512) |
| `feature-graphic-1024x500.png` | Store listing → Feature graphic |
| `phone-*.png` | Store listing → Phone screenshots (at least 2) |
| https://smart-bus-48vw.onrender.com/privacy.html | App content → Privacy policy URL |

## Store listing text

**App name:** Smart Bus

**Short description (≤ 80 characters):**
Book your college bus seat, pay your transport fee and track your bus live.

**Full description:**
Smart Bus makes the college bus simple.

• Book your seat: tell the college each evening whether you'll take the bus tomorrow. One tap.
• Know your bus: see which bus picks you up, the stop order, and where your stop is.
• Track it live: watch your bus on the map with an arrival time for your stop. No more waiting in the sun.
• Pay your fee: pay your transport fee securely online (UPI, cards, net banking) and get an instant receipt.
• For drivers: see today's route and share your location with the students on your bus.

For colleges, Smart Bus combines stops into the fewest buses that fit everyone without exceeding seats,
saving fuel every day, and shows the transport office live buses, payments and savings.

Your college must be using Smart Bus. Log in with your college Student ID.

**Category:** Education (or Maps & Navigation) · **Tags:** transport, college, bus tracking

## App content answers (Policy → App content)

- **Privacy policy:** https://smart-bus-48vw.onrender.com/privacy.html
- **Ads:** No ads.
- **App access:** Login required. Give reviewers a demo account:
  student `22B81A020007` / `student123`, driver `driver1` / `driver123`, admin `admin` / `admin123`.
  (Demo data resets when the server restarts. Keep at least one open trip before submitting.)
- **Target audience:** 18 and over (plus 16–17 if your colleges have younger first-years). Not for children.
- **Content rating:** complete the questionnaire. No violence, user-generated content or gambling,
  so expect "Everyone" / "3+".
- **Location permission:** used only in the foreground, while a driver shares a trip. No background
  location, so no background-location declaration is needed.
- **Financial features:** the app takes payments for a real-world service (transport fees) through
  Razorpay. This is allowed outside Google Play Billing because it's a physical service, not digital goods.

### Data safety form

| Data type | Collected | Shared | Purpose | Optional? |
|---|---|---|---|---|
| Name, user IDs (Student ID) | Yes | With the college | App functionality, account management | Required |
| Precise location | Yes (drivers only) | With students on that bus and the college | App functionality | Optional (drivers can stop sharing) |
| Phone number | Yes (at payment, by Razorpay) | Razorpay | Payments | Required for online payment |
| Purchase history (fee payments) | Yes | With the college, Razorpay | App functionality | Required for online payment |
| App interactions (ride Yes/No choices) | Yes | With the college | App functionality | Required |

- Data is **encrypted in transit** (HTTPS): Yes.
- Users can **request deletion**: Yes, through the college transport office.
- No data is sold or used for advertising.

## Release steps

1. Create a Google Play developer account (one-time $25): https://play.google.com/console
2. **Create app** → name "Smart Bus", default language English (India), App, Free.
3. Fill in **Store listing** and **App content** using the text above.
4. **Testing → Internal testing → Create release** → upload `app-release.aab`.
   Keep **Play App Signing** on: Google holds the app-signing key, and your file only proves uploads.
5. Add testers (your Gmail addresses), roll out, and install from the opt-in link.
6. When it works, promote the release to **Production**. New personal developer accounts must first
   run a closed test with at least 12 testers for 14 days.

## Updating the app

The app loads the live website, so most updates need **no new store release**: push to `main`, and
Render deploys it. Build a new `.aab` only when the native shell changes (icon, permissions, URL, plugins):

```bash
# bump versionCode (+1) and versionName in mobile/android/app/build.gradle, then:
cd mobile/android
gradlew bundleRelease       # signed with keystore.properties
```

## ⚠ The upload key

`mobile/android/keystore/smartbus-upload.jks` and `mobile/android/keystore.properties` (password)
sign every upload. They are **not in git**. A backup is in `Documents/SmartBus-signing-key-BACKUP`.
Copy that folder somewhere safe (an encrypted drive or password manager). With Play App Signing on, a lost
upload key can be reset through Google support, but that takes days.
