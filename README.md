# UniRCm

UniRCm (Uni Remote Connection Manager) is a desktop app for system administrators who use SSH, Telnet, and remote desktops. Open a Linux server shell, connect to a legacy switch, and use a Windows desktop over RDP from the same app.

## What you can do

- Open SSH and Telnet terminals and RDP desktops in tabs. The Debian and Ubuntu packages include the FreeRDP 3 bridge.
- Save connections in folders and reuse credentials across profiles. UniRCm stores settings and saved credentials in a SQLCipher database protected by a master password.
- Browse remote directories and transfer files from an SSH session that's already open.

Telnet sends credentials and session data without encryption. Use SSH when the device supports it.

## Screenshots

**Connection manager** with example SSH and RDP profiles organized in groups.

![UniRCm main window showing the grouped connection tree and session toolbar](docs/screenshots/connection-manager.png)

**RDP profile editor** showing the destination and authentication settings for an embedded desktop.

![UniRCm profile editor showing an example RDP connection with the password field empty](docs/screenshots/rdp-profile.png)

**SSH file manager** showing remote folders, file sizes, modification times, and permissions.

![UniRCm SSH file manager showing the remote places sidebar, icon toolbar, and detailed file list](docs/screenshots/ssh-file-manager.png)

## Transfer files over SSH

Once you're connected, right-click inside the SSH terminal and choose **File manager** to browse remote folders and download selected files. Choose **Upload file** or drop local files onto the terminal to start an upload. UniRCm uses SFTP over the existing authenticated SSH connection, so you can move files without logging in again or opening a separate client. The server must support SFTP.

## Run from source

On Linux, open a terminal in the repository folder. You'll need a graphical desktop, Python 3.11 or later, and the OpenSSH client.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
unircm
```

On first launch, create a master password. Then use **File → New connection** to save a profile and double-click it to connect.

When creating a `.uni` archive, you can also generate or select a key file.
To add, replace or remove one later, open **Database settings → Change vault
protection**. Keep a separate copy of each key file you need. If you lose a
required file, you lose access to the archive and any backup that requires it.

To enable RDP, install a C compiler, `pkg-config`, and the FreeRDP 3 and WinPR 3 development libraries. With the virtual environment active, run:

```sh
python -m remote_manager.protocols.build_rdp
```

See the [installation and packaging guide](docs/installation.md) for development setup and Debian package builds.

## Project status

UniRCm is in development on Linux. FreeBSD is a target and still needs testing. VNC is experimental. A future version may support HTTPS for device and server admin pages.

## License

UniRCm is licensed under [GPL-3.0-or-later](LICENSE). See the bundled artwork's [license](src/remote_manager/ui/assets/papirus/LICENSE) and [sources](src/remote_manager/ui/assets/papirus/SOURCES.json).
