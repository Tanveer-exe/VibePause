# Privacy Policy for VibePause

Last updated: October 17, 2026

This policy covers the VibePause Windows application (the "App") and the VibePause website at https://tanveer-exe.github.io/VibePause/ (the "Website"). Together they are the "Service". The Service is operated by tanveer-exe ("we", "us" or "our"), an individual developer based in India. VibePause is a free, non-commercial, open-source project.

## Summary

- The App runs on your computer. It has no account, no analytics, no advertising, no tracking and no cookies, and it does not send us any data.
- The App connects to the internet only to check for and download updates from GitHub.
- The Website has no cookies, no analytics, no advertising, no tracking and no forms. Because it is hosted on GitHub Pages, GitHub receives your IP address and browser details when you visit it.
- We do not sell or share personal data, because we do not receive it.

## Who is responsible

tanveer-exe, an individual (https://github.com/Tanveer-exe). The way to contact us is to open an issue at https://github.com/Tanveer-exe/VibePause/issues. Issues are public, so please do not put personal information in one.

## The App

### Data the App does not collect

- Your name, email address, phone number or address
- Your Riot Games account details, passwords or authentication tokens
- Game memory, screenshots or gameplay input
- Usage statistics or analytics
- Crash reports. The App never sends them anywhere (see the error log below)
- The titles, artists or artwork of what you play. The App shows these in its window while something is playing, but keeps them only in memory, never writes them to disk or the error log, and never sends them anywhere

### Data stored on your computer

The App saves your settings in a file named `settings.json` in the `Documents\VibePause` folder. This file contains your chosen actions for each game event, the event delay, your startup and tray preferences, your update check preference, the optional hotkey you chose (none by default), your language and mode (pause or volume), the volume levels you set, whether the spinning cover is on, and which version of the legal terms you accepted.

This file stays on your computer. It is never uploaded. Uninstalling VibePause keeps this file so your settings survive a reinstall. You can delete the folder yourself at any time.

If something goes wrong, the App may also write technical error details (such as an error message, the app version and your Windows and Python version) to a file named `error.log` in the same folder. This file helps you report a problem if you choose to, but it stays on your computer and is never uploaded or sent automatically.

The Settings screen has two support buttons. Open log folder opens this folder in Windows Explorer. Copy diagnostics puts a short report on your clipboard: the app and Windows versions, your settings, recent activity and the end of `error.log`, with your Windows user name removed from file paths. Nothing is sent anywhere unless you paste it somewhere yourself, for example into a public GitHub issue. Please read it before you post it.

### What the App reads on your computer

- The VALORANT game log file (`ShooterGame.log`), read locally to detect game events such as a round starting. Nothing from this file is sent anywhere.
- While Windows OCR death detection is enabled, the App temporarily captures the screen during an active combat round and uses the built-in Windows OCR engine to look for the "KILLED BY" banner. Screenshots are processed in memory, not saved to disk, and never uploaded or transmitted.
- Windows media sessions. The App uses them to play, pause, skip and show what is playing: the title, artist, album and artwork that your media app shares with Windows. This is used only to draw the now-playing card and is not stored or sent anywhere.
- In volume mode, which apps are playing sound, and their volume, using the same Windows audio information as the volume mixer. The App only changes the volume of those apps, never changes VALORANT, Riot software, voice chat or call apps, and puts the volumes back when you leave volume mode or exit. This stays on your computer.
- If you set a hotkey, the App asks Windows to tell it when that one key combination is pressed, only so it can turn itself on or off. It does not record or read any other keystrokes.

### Network use

The App connects to the internet only to check for and download updates from GitHub (github.com and api.github.com). These requests carry the app name and version in the request header, and GitHub will see your IP address as with any web request. No other information is sent.

If you turn off automatic update checks, the App only contacts GitHub when you click Check for updates.

GitHub's handling of that connection is covered by the GitHub Privacy Statement.

## The Website

- The Website sets no cookies and does not use local storage or similar technologies. See the Cookie Policy at https://tanveer-exe.github.io/VibePause/cookies.html.
- The Website has no analytics, advertising, tracking pixels, social media widgets, login or contact forms, and it does not embed third-party content such as videos or maps. It does not load fonts or scripts from third parties.
- The Website is hosted by GitHub Pages. GitHub, as the host, receives technical information such as your IP address, browser type and the time of your visit, and may keep it in server logs. We do not receive or use these logs.
- To show the latest version number and the language breakdown, a script on the page asks api.github.com for public information about this repository. This makes a request from your browser to GitHub, which sees your IP address. No personal data is sent to us.
- The download button and other links go to GitHub, Ko-fi and SignPath. When you follow them you leave the Website, and their own privacy policies apply.

## Donations

Donations are voluntary and handled by Ko-fi (https://ko-fi.com), not by the App or the Website. Ko-fi, not us, collects and processes payment details. We may see what Ko-fi shows creators about a donation, such as the name, message and amount you provide. See the Terms and Conditions at https://tanveer-exe.github.io/VibePause/terms.html for more about donations.

## Reporting a problem on GitHub

If you open a GitHub issue, what you write, including anything you paste from Copy diagnostics, is public and is handled by GitHub under its own terms and privacy statement. Do not include personal information or anything you want kept private.

## Sharing of data

We do not share your data with anyone because we do not receive it through the App or the Website.

## Your rights

Depending on where you live, you may have rights over your personal data, such as access, correction, deletion or objection (for example under the EU and UK GDPR, India's Digital Personal Data Protection Act, 2023, or US state laws). We do not hold personal data about you from the App or the Website, so there is normally nothing for us to give you, correct or delete. For data held by GitHub or Ko-fi, please contact them. For anything else, open an issue and we will respond. If you are in the EU or UK you may also complain to your local data protection authority.

## Security

Because your settings never leave your computer, their security depends on your own device and account. The update installer is downloaded from the official GitHub release over HTTPS, and the App checks it against the checksum GitHub publishes for the release file before it starts the installer. The installer is not yet code-signed, so Windows may warn you when you run it (see the Code Signing Policy in the project repository).

## Children's privacy

VibePause does not collect personal data from anyone, including children, and is not directed at children.

## Where data goes

GitHub is based in the United States, so a connection from the App or the Website to GitHub may be handled outside your country.

## Changes to this Privacy Policy

We may update this Privacy Policy from time to time. Changes are posted with the App, on the Website and on the project's GitHub page, and the date at the top is updated. When the policy bundled with the App changes, the App asks you to review and accept it again.

## Contact us

If you have any questions about this Privacy Policy, please open an issue at https://github.com/Tanveer-exe/VibePause/issues.
