Werkbank - portable app for Windows
===================================

Nothing to install and no administrator rights needed.

Start
-----
1. Extract the whole zip file to a folder you can write to, for example
   Documents\Werkbank. (Do not run it from inside the zip.)
2. Double-click Werkbank.exe. A window opens that runs Werkbank, and your
   browser opens http://127.0.0.1:8765.
3. To stop Werkbank, close that window.

The first time, Windows may say "Windows protected your PC", because the app
is not signed by a publisher Windows knows. Click "More info", then
"Run anyway". This needs no administrator rights.

Your files
----------
Files are processed on this computer only; nothing is uploaded.
  Inbox and Outbox:  Werkbank folder in your user folder (C:\Users\<you>\Werkbank)
  Settings:          %APPDATA%\Werkbank\config.json
To remove Werkbank, delete its folder and the two folders above.

Updating
--------
- yt-dlp (the downloader) changes often: use "Update yt-dlp" on the Status page.
  This needs the bin folder to be writable, which is why you extract it
  somewhere in your user folder.
- For a new version of Werkbank, download the latest zip, close Werkbank and
  replace the folder.

Included programs
-----------------
bin\ contains FFmpeg, FFprobe, Deno and yt-dlp. Their versions, licences and
source code locations are listed in THIRD-PARTY.txt and the licences folder.
