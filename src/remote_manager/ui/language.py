"""English default and Italian Qt translations; language is stored in the vault."""
from PyQt6.QtCore import QObject, QEvent, QTranslator
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (QAbstractButton, QApplication, QDialog, QLabel,
                            QMainWindow, QMenu, QTreeWidget, QLineEdit, QPushButton, QStyle)

# Shared wording across dialogs and protocols. User-entered text is not translated.
ITALIAN = dict(line.split('\t', 1) for line in '''Connection details\tDettagli connessione
Destination\tDestinazione
Authentication\tAutenticazione
Group details\tDettagli gruppo
SSH defaults\tImpostazioni SSH predefinite
Connections can inherit a shared credential from this group.\tLe connessioni possono ereditare una credenziale condivisa da questo gruppo.
Choose which settings connections inherit from this group.\tScegli quali impostazioni le connessioni ereditano da questo gruppo.
Save connection\tSalva connessione
Create connection\tCrea connessione
Save group\tSalva gruppo
Create group\tCrea gruppo
Save settings\tSalva impostazioni
Credential details\tDettagli credenziale
Enter a credential name.\tInserisci un nome per la credenziale.
Enter a hostname or SSH alias.\tInserisci un nome host o un alias SSH.
Show passwords\tMostra password
Show or hide the password and private-key passphrase.\tMostra o nasconde la password e la passphrase della chiave privata.
Show or hide the entered master passwords.\tMostra o nasconde le password principali inserite.
Master password\tPassword principale
The current password is required to protect the encrypted database with a new password.\tLa password attuale è necessaria per proteggere il database cifrato con una nuova password.
Enter the current master password.\tInserisci la password principale attuale.
Enter a new master password.\tInserisci una nuova password principale.
General settings\tImpostazioni generali
Security\tSicurezza
Appearance and maintenance\tAspetto e manutenzione
These actions save their changes immediately.\tQueste azioni salvano immediatamente le modifiche.
Routing\tInstradamento
Connection health\tControllo connessione
Authentication and transport\tAutenticazione e trasporto
OpenSSH options\tOpzioni OpenSSH
Drag to resize; click the dots to show or hide the connections panel.\tTrascina per ridimensionare; fai clic sui puntini per mostrare o nascondere il pannello delle connessioni.
Show or hide the connections panel.\tMostra o nasconde il pannello delle connessioni.
Your remote connections, securely organized.\tLe tue connessioni remote, organizzate in sicurezza.
Unlock error\tErrore di sblocco
Unlock the database with its master password.\tSblocca il database con la password principale.
Database locked\tDatabase bloccato
Close the application.\tChiude l’applicazione.
Back to databases\tTorna ai database
Return to the database list.\tTorna all’elenco dei database.
Text clipboard ready.	Appunti di testo pronti.
Text clipboard enabled; waiting for the server.	Appunti di testo abilitati; in attesa del server.
Share text clipboard	Condividi appunti di testo
Share text only while this desktop has focus. Other clipboard formats and file transfers are disabled.	Condivide solo testo mentre questo desktop ha il focus. Altri formati e trasferimenti di file sono disabilitati.
Fullscreen	Schermo intero
Exit fullscreen	Esci da schermo intero
Return to the previous view (Ctrl+Alt+Enter).	Torna alla vista precedente (Ctrl+Alt+Invio).
Toggle fullscreen without reconnecting (Ctrl+Alt+Enter).	Attiva o disattiva lo schermo intero senza riconnettere (Ctrl+Alt+Invio).
Connections	Connessioni
Workspace	Spazio di lavoro
Layout	Disposizione
Split vertically	Dividi verticalmente
Split horizontally	Dividi orizzontalmente
No other active sessions	Nessun’altra sessione attiva
Drop a connection or an open session here.	Trascina qui una connessione o una sessione aperta.
Drag this session to another workspace tab.	Trascina questa sessione sulla scheda di un altro spazio di lavoro.
Hold Shift and drag to move the active session to another workspace.	Tieni premuto Maiusc e trascina per spostare la sessione attiva in un altro spazio di lavoro.
Side by side	Affiancati
Stacked	Sovrapposti
Grid 2 × 2	Griglia 2 × 2
Apply layout	Applica disposizione
Add connection	Aggiungi collegamento
Move open session here	Sposta qui una sessione aperta
Rename tab	Rinomina scheda
Detach active pane	Separa pannello attivo
Close active pane	Chiudi pannello attivo
Maximize	Ingrandisci
Detach	Separa
Enlarge this pane or restore the layout.	Ingrandisce questo pannello o ripristina la disposizione.
Move this session into its own tab without reconnecting.	Sposta questa sessione in una scheda separata senza riconnetterla.
Disconnect and close only this pane.	Disconnette e chiude solo questo pannello.
Disconnect and close this pane?	Disconnettere e chiudere questo pannello?
Disconnect all active sessions in this tab and close it?	Disconnettere tutte le sessioni attive in questa scheda e chiuderla?
SSH file transfer	Trasferimento file SSH
Wait for the current operation before uploading more files.	Attendi il completamento dell’operazione prima di caricare altri file.
Transfer cancelled.	Trasferimento annullato.
Temporary upload could not be removed: %1. Check the connection and remove this file manually.	Impossibile eliminare il file temporaneo: %1. Controlla la connessione ed elimina manualmente questo file.
Upload file	Carica file
Download file	Scarica file
Remote directory (independent of the terminal):	Cartella remota (indipendente dal terminale):
Open directory	Apri cartella
Parent directory	Cartella superiore
Bytes	Byte
Directory	Cartella
File	File
An active SSH connection is required.	È necessaria una connessione SSH attiva.
Transfer failed: 	Trasferimento non riuscito:\x20
Reading remote directory…	Lettura della cartella remota…
Select files to download, or upload local files.	Seleziona i file da scaricare oppure carica file locali.
Only regular files can be transferred.	È possibile trasferire solo file regolari.
Files with the same name must be uploaded separately.	I file con lo stesso nome devono essere caricati separatamente.
Upload these files to: 	Carica questi file in:\x20
Replace existing files?	Sostituire i file esistenti?
Select regular files to download.	Seleziona i file da scaricare.
Download destination	Destinazione del download
Transfer completed.	Trasferimento completato.
bytes	byte
Cancelling…	Annullamento…
Connect at startup	Collega all’avvio
Open this connection automatically after unlocking the database at application startup.	Apre automaticamente questo collegamento dopo lo sblocco dell’archivio all’avvio dell’applicazione.
New connection	Nuova connessione
New group	Nuovo gruppo
New subgroup	Nuovo sottogruppo
New	Nuovo
Edit	Modifica
Move	Sposta
Duplicate	Duplica
Delete	Elimina
Connect	Connetti
Lock	Blocca
Settings	Impostazioni
Credentials	Credenziali
Open database	Apri database
Group properties…	Proprietà gruppo…
Group properties	Proprietà gruppo
Edit connection	Modifica connessione
General	Generale
Appearance	Aspetto
Terminal	Terminale
Connection name	Nome connessione
Group	Gruppo
Hostname / SSH alias	Nome host / alias SSH
Protocol	Protocollo
Username	Nome utente
Password	Password
Private-key passphrase (SSH)	Passphrase chiave privata (SSH)
Credential source	Origine credenziali
Shared credential	Credenziale condivisa
Connection credentials	Credenziali della connessione
Inherit from group	Eredita dal gruppo
Inherit from parent	Eredita dal gruppo superiore
No shared credential	Nessuna credenziale condivisa
Select credential…	Seleziona credenziale…
Inherited credential: 	Credenziale ereditata:\x20
None	Nessuna
Override	Personalizza
Application default	Predefinito dell'applicazione
Port	Porta
Private key	Chiave privata
Connection timeout	Timeout connessione
Timeout	Timeout
Browse…	Sfoglia…
Import key…	Importa chiave…
Install public key…	Installa chiave pubblica…
Install public key	Installa chiave pubblica
Install this public key in ~/.ssh/authorized_keys for the active SSH account on %1?	Installare questa chiave pubblica in ~/.ssh/authorized_keys per l’account SSH attivo su %1?
Authorize this public key for future SSH logins.	Autorizza questa chiave pubblica per i prossimi accessi SSH.
Authorize the public key from this profile’s vault on the connected server.	Autorizza la chiave pubblica del profilo sul server connesso.
Import a private key into this SSH profile first.	Importa prima una chiave privata in questo profilo SSH.
Unable to derive the public key from the imported OpenSSH key.	Impossibile ricavare la chiave pubblica dalla chiave OpenSSH importata.
Installing public key…	Installazione della chiave pubblica…
Public key installed in ~/.ssh/authorized_keys.	Chiave pubblica installata in ~/.ssh/authorized_keys.
This public key is already authorized on the server.	Questa chiave pubblica è già autorizzata sul server.
Public key installation could not be confirmed. Check the SSH session and remote authorized_keys.	Impossibile confermare l’installazione della chiave pubblica. Controlla la sessione SSH e il file authorized_keys remoto.
Imported: %1	Importata: %1
Remove imported key	Rimuovi chiave importata
Use a private key from its file path.	Usa una chiave privata dal suo percorso.
Copy an OpenSSH private key into the encrypted database when you save.	Copia una chiave privata OpenSSH nel database cifrato al salvataggio.
Remove this connection’s imported key from the database when you save.	Rimuove la chiave importata per questa connessione dal database al salvataggio.
Imported SSH keys require Linux with /proc available.	Le chiavi SSH importate richiedono Linux con /proc disponibile.
Unable to read the selected SSH private key.	Impossibile leggere la chiave privata SSH selezionata.
Select an OpenSSH private key file up to 128 KiB.	Seleziona un file di chiave privata OpenSSH di massimo 128 KiB.
Unable to validate the selected SSH key with ssh-keygen.	Impossibile verificare la chiave SSH selezionata con ssh-keygen.
The selected OpenSSH private key could not be read by ssh-keygen.	ssh-keygen non riesce a leggere la chiave privata OpenSSH selezionata.
Unable to open an anonymous file for the SSH key.	Impossibile aprire un file anonimo per la chiave SSH.
Connection icon	Icona connessione
Tab label color	Colore etichetta scheda
Choose color…	Scegli colore…
Use default	Usa predefinito
Choose…	Scegli…
Save	Salva
Cancel	Annulla
Close	Chiudi
OK	OK
Apply	Applica
Yes	Sì
No	No
Reset	Ripristina
Font	Carattere
Font size	Dimensione carattere
Background	Sfondo
Text	Testo
Cursor	Cursore
Cursor color	Colore cursore
Cursor shape	Forma cursore
Blinking cursor	Cursore lampeggiante
Outline	Contorno
Block	Blocco
Underline	Sottolineatura
Bar	Barra
Size	Dimensione
On	Attivo
Off	Disattivo
Terminal type	Tipo di terminale
Encoding	Codifica
Login mode	Modalità di accesso
Username prompt	Prompt nome utente
Password prompt	Prompt password
Manual login — do not send stored credentials	Accesso manuale — non inviare credenziali salvate
Send password only at password prompt	Invia solo la password al relativo prompt
Send username and password at login prompts	Invia nome utente e password ai rispettivi prompt
Automatic (login:, username:)	Automatico (login:, username:)
Automatic (password:)	Automatico (password:)
Telnet — unencrypted	Telnet — non cifrato
Choose SSH or Telnet. Telnet sends credentials and session data without encryption.	Scegli SSH o Telnet. Telnet invia credenziali e dati della sessione senza cifratura.
Telnet is unencrypted: credentials and session data are sent in clear text. Stored credentials are sent only when an automatic login mode is explicitly selected.	Telnet non è cifrato: credenziali e dati della sessione vengono inviati in chiaro. Le credenziali salvate sono inviate solo selezionando esplicitamente una modalità di accesso automatico.
Literal text expected at the end of the prompt line, ignoring letter case. Leave blank for automatic detection. Not a regular expression.	Testo letterale atteso alla fine della riga del prompt, senza distinzione tra maiuscole e minuscole. Lascia vuoto per il riconoscimento automatico. Non è un'espressione regolare.
Shared credentials	Credenziali condivise
New credential	Nuova credenziale
Edit credential	Modifica credenziale
Delete credential	Elimina credenziale
Name	Nome
Delete selected shared credential?	Eliminare la credenziale condivisa selezionata?
Select a shared credential.	Seleziona una credenziale condivisa.
Credential is in use. Remove connection and group references first.	La credenziale è in uso. Rimuovi prima i riferimenti dalle connessioni e dai gruppi.
Group name	Nome gruppo
Parent group	Gruppo superiore
Destination	Destinazione
Search name, host or username…	Cerca nome, host o utente…
Connecting	Connessione in corso
Authenticating	Autenticazione in corso
Connected	Connesso
Disconnected	Disconnesso
Error	Errore
Unknown	Sconosciuto
No active tab	Nessuna scheda attiva
Connection protocol	Protocollo di connessione
Connection duration since successful authentication	Durata della connessione dall'autenticazione
Terminal: %1 columns × %2 rows	Terminale: %1 colonne × %2 righe
Desktop: %1 × %2 pixels	Desktop: %1 × %2 pixel
Exit code: %1	Codice di uscita: %1
Session process exit code	Codice di uscita del processo della sessione
Copy selection	Copia selezione
Copy screen	Copia schermata
Paste	Incolla
Copy	Copia
Terminal appearance…	Aspetto del terminale…
Reconnect	Riconnetti
disconnected	disconnesso
error	errore
Telnet connection closed	Connessione Telnet chiusa
Telnet connection error	Errore connessione Telnet
Database settings	Impostazioni database
Inactivity lock	Blocco per inattività
Disabled	Disabilitato
 min	 min
 s	 s
Language	Lingua
English	Inglese
Italian	Italiano
Archive description	Descrizione archivio
Public archive description, visible before unlocking. Do not enter credentials or sensitive information.	Descrizione pubblica dell'archivio, visibile prima dello sblocco. Non inserire credenziali o informazioni riservate.
Change master password…	Cambia password principale…
Change master password	Cambia password principale
Current master password	Password principale attuale
New master password	Nuova password principale
Confirm new master password	Conferma nuova password principale
New passwords do not match.	Le nuove password non coincidono.
Current master password is incorrect.	La password principale attuale non è corretta.
Choose a different new master password.	Scegli una nuova password principale diversa.
Enter nonempty master passwords without NUL characters.	Inserisci password principali non vuote e prive di caratteri NUL.
Unable to change the master password.	Impossibile cambiare la password principale.
Unable to save encrypted database settings.	Impossibile salvare le impostazioni cifrate del database.
Enabling inactivity lock closes active sessions and open editors automatically when the timeout expires.	Il blocco per inattività chiude automaticamente le sessioni attive e le finestre di modifica allo scadere del tempo.
Automatically disconnects all sessions and locks this database after no keyboard or mouse activity. Remote output does not reset the timeout.	Disconnette tutte le sessioni e blocca il database dopo un periodo senza attività di tastiera o mouse. L'output remoto non azzera il tempo.
Requires the current master password and verifies the encrypted database with the new password.	Richiede la password principale attuale e verifica il database cifrato con la nuova password.
Open configuration database	Apri database di configurazione
Choose an independent database for home, work or a customer.	Scegli un database indipendente per casa, lavoro o un cliente.
Description	Descrizione
Location	Posizione
Last modified	Ultima modifica
Unavailable	Non disponibile
Unlock selected	Sblocca selezionato
Open file…	Apri file…
New database…	Nuovo database…
Remove from list	Rimuovi dall'elenco
Unlock Database	Sblocca database
Unlock database	Sblocca database
Create encrypted database	Crea database cifrato
Master password	Password principale
Confirm password	Conferma password
Show password	Mostra password
New database	Nuovo database
Create database	Crea database
Public description (visible without password):	Descrizione pubblica (visibile senza password):
Database unavailable	Database non disponibile
The selected file does not exist.	Il file selezionato non esiste.
File exists	Il file esiste
Choose a new filename. Existing databases cannot be overwritten.	Scegli un nuovo nome file. I database esistenti non possono essere sovrascritti.
Database already open	Database già aperto
This database is already open in the current window.	Questo database è già aperto nella finestra attuale.
Close the database chooser.	Chiudi la selezione del database.
Close active connection	Chiudi collegamento attivo
This connection is still active. Disconnect and close the tab?	Questo collegamento è ancora attivo. Disconnetterlo e chiudere la scheda?
Disconnect sessions	Disconnetti sessioni
Disconnect all active sessions?	Disconnettere tutte le sessioni attive?
Save failed	Salvataggio non riuscito
Delete failed	Eliminazione non riuscita
Duplicate failed	Duplicazione non riuscita
Move failed	Spostamento non riuscito
Invalid group	Gruppo non valido
Delete group	Elimina gruppo
Delete connection	Elimina connessione
Connection could not start	Impossibile avviare la connessione
Database switch failed	Cambio database non riuscito
Unable to close the current encrypted database.	Impossibile chiudere il database cifrato attuale.
'''.splitlines())


ITALIAN.update(dict(line.split('\t', 1) for line in ''' (unavailable or invalid)	 (non disponibile o non valido)
 — Unencrypted connection	 — Connessione non cifrata
#RRGGBB (blank: default)	#RRGGBB (vuoto: predefinito)
Appearance changes also update open terminals. SSH changes apply to new sessions.	Le modifiche all'aspetto aggiornano anche i terminali aperti. Le impostazioni SSH si applicano alle nuove sessioni.
Automatic login sends each stored field once at its configured prompt, or a recognized prompt when blank. Other prompts and retries require manual input. Credentials come from General, including group inheritance.	L'accesso automatico invia ogni campo salvato una sola volta al prompt configurato, oppure a un prompt riconosciuto se vuoto. Altri prompt e nuovi tentativi richiedono l'inserimento manuale. Le credenziali provengono da Generale, inclusa l'ereditarietà dai gruppi.
Blank overrides use OpenSSH configuration/agent.	I valori personalizzati vuoti usano la configurazione OpenSSH o l'agente.
Blink cursor	Cursore lampeggiante
Changes are previewed in the current session.	Le modifiche sono visualizzate in anteprima nella sessione attuale.
Choose tab color	Scegli colore scheda
Choose terminal color	Scegli colore terminale
Duration since Telnet connection was established; login status is unknown.	Durata dalla connessione Telnet; lo stato dell'accesso non è noto.
Font size (pt)	Dimensione carattere (pt)
Last modification time of the database file (local time).	Ultima modifica del file del database (ora locale).
Limits connection establishment and the initial SSH handshake. Does not limit session duration.	Limita il tempo di connessione e la negoziazione SSH iniziale. Non limita la durata della sessione.
Local connection result: 0 means closed, 1 means transport error. Telnet does not provide remote command exit codes.	Esito locale della connessione: 0 indica chiusura, 1 errore di trasporto. Telnet non fornisce codici di uscita dei comandi remoti.
Manage shared encrypted credentials	Gestisci le credenziali cifrate condivise
Restore defaults	Ripristina predefiniti
SSH	SSH
SSH authentication	Autenticazione SSH
SSH private-key passphrase, stored in the common encrypted credential. Select or import the matching private key in SSH properties. Other protocols do not send it. Automatic key unlocking disables SSH keyboard-interactive authentication for this session.	Passphrase della chiave privata SSH, salvata nella credenziale cifrata comune. Seleziona o importa la chiave corrispondente nelle proprietà SSH. Gli altri protocolli non la inviano. Lo sblocco automatico della chiave disabilita l'autenticazione SSH keyboard-interactive per questa sessione.
Save for this connection	Salva per questa connessione
Select private key	Seleziona chiave privata
Stored only in the encrypted database. Leave empty to authenticate interactively or with a key/agent.	Salvata solo nel database cifrato. Lascia vuoto per autenticarti manualmente o con una chiave/agente.
Telnet	Telnet
Telnet — unencrypted TCP connection; authentication is handled by the remote device.	Telnet — connessione TCP non cifrata; l'autenticazione è gestita dal dispositivo remoto.
Terminal appearance	Aspetto del terminale
Unable to delete encrypted credential.	Impossibile eliminare la credenziale cifrata.
Unable to save connection to the encrypted database.	Impossibile salvare la connessione nel database cifrato.
Unable to save encrypted credential.	Impossibile salvare la credenziale cifrata.
Unable to save group to the encrypted database.	Impossibile salvare il gruppo nel database cifrato.
Unable to save terminal appearance to the encrypted database.	Impossibile salvare l'aspetto del terminale nel database cifrato.
Username used to authenticate to the remote server.	Nome utente per l'autenticazione sul server remoto.
Uses the common credentials, OpenSSH config and agent. Leave the password empty for interactive authentication. Host keys are verified by OpenSSH.	Usa le credenziali comuni, la configurazione OpenSSH e l'agente. Lascia la password vuota per l'autenticazione manuale. OpenSSH verifica le chiavi host.
Choose an existing database file to unlock.	Scegli un database esistente da sbloccare.
Connection no longer exists.	La connessione non esiste più.
Connection timeout (seconds)	Timeout connessione (secondi)
Create a new encrypted database with a description and master password.	Crea un database cifrato con descrizione e password principale.
Default color	Colore predefinito
Default terminal appearance	Aspetto predefinito del terminale
Edit selected connection	Modifica la connessione selezionata
Edit selected group properties	Modifica le proprietà del gruppo selezionato
Enter a connection name.	Inserisci un nome per la connessione.
Enter a group name.	Inserisci un nome per il gruppo.
Enter a master password.	Inserisci una password principale.
Forget the selected database without deleting its file.	Rimuovi il database selezionato dall'elenco senza eliminarne il file.
Group defaults	Valori predefiniti del gruppo
Inherited from %1	Ereditato da %1
No group (root)	Nessun gruppo (radice)
OpenSSH configuration / agent	Configurazione OpenSSH / agente
Passwords do not match.	Le password non coincidono.
Password strength	Robustezza della password
Key derivation iterations	Iterazioni di derivazione della chiave
Higher values slow down both unlocking and offline password guessing.	Valori più alti rallentano lo sblocco e i tentativi offline di indovinare la password.
Estimates strength from password length and character variety.	Stima la robustezza in base alla lunghezza e alla varietà dei caratteri.
Weak	Debole
Medium	Media
Strong	Forte
Protects all saved connection profiles. Password recovery is unavailable.	Protegge tutti i profili di connessione salvati. Non è possibile recuperare la password.
Select a group to edit SSH defaults.	Seleziona un gruppo per modificare i valori predefiniti SSH.
Set master password	Imposta password principale
Unable to delete connection.	Impossibile eliminare la connessione.
Unable to delete group.	Impossibile eliminare il gruppo.
Unable to duplicate connection in the encrypted database.	Impossibile duplicare la connessione nel database cifrato.
Unable to move the connection.	Impossibile spostare la connessione.
Unable to unlock database. Check the password and database access.	Impossibile sbloccare il database. Controlla la password e l'accesso al database.
The archive has changed. Its encrypted working copy was preserved.	L’archivio è cambiato. La copia di lavoro cifrata è stata conservata.
Unlock the selected database with its master password.	Sblocca il database selezionato con la password principale.
Server	Server
Router	Router
Switch	Switch
Access point	Access point
Firewall	Firewall
Laptop	Portatile
PC	PC
Database	Database
Enter a credential name.	Inserisci un nome per la credenziale.
Select an existing shared credential.	Seleziona una credenziale condivisa esistente.
Invalid credential source.	Origine delle credenziali non valida.
Password cannot contain NUL or line breaks.	La password non può contenere caratteri NUL o ritorni a capo.
Group no longer exists.	Il gruppo non esiste più.
A group cannot be moved into itself or one of its subgroups.	Un gruppo non può essere spostato in sé stesso o in un proprio sottogruppo.
Invalid username.	Nome utente non valido.
Invalid SSH port.	Porta SSH non valida.
SSH connection timeout must be between 1 and 600 seconds.	Il timeout SSH deve essere compreso tra 1 e 600 secondi.
Invalid color: use #RRGGBB.	Colore non valido: usa #RRGGBB.
Invalid Telnet settings.	Impostazioni Telnet non valide.
Invalid Telnet terminal type.	Tipo di terminale Telnet non valido.
Unsupported Telnet encoding.	Codifica Telnet non supportata.
Invalid Telnet login mode.	Modalità di accesso Telnet non valida.
Invalid Telnet port.	Porta Telnet non valida.
Telnet prompts must contain at most 256 characters without control characters.	I prompt Telnet possono contenere al massimo 256 caratteri, senza caratteri di controllo.
Telnet connection failed or was interrupted.	La connessione Telnet non è riuscita o è stata interrotta.
Telnet input buffer is full; connection closed.	Il buffer di input Telnet è pieno; connessione chiusa.
Stored credentials cannot be encoded with the selected Telnet encoding; use manual login.	Le credenziali salvate non sono rappresentabili con la codifica Telnet selezionata; usa l'accesso manuale.
Enter a hostname or IP address without spaces.	Inserisci un nome host o un indirizzo IP senza spazi.
Enter a hostname, SSH alias or IP address without spaces.	Inserisci un nome host, un alias SSH o un indirizzo IP senza spazi.'''.splitlines()))


ITALIAN.update({'Inherited value: %1': 'Valore ereditato: %1', 'Default value: %1': 'Valore predefinito: %1'})

ITALIAN.update({
    'Drag above or below an item to reorder; drop onto a group to move inside it.': "Trascina sopra o sotto un elemento per riordinarlo; rilascia su un gruppo per spostarlo al suo interno.",
    'Sort the selected group contents by name, with groups before connections.': 'Ordina il contenuto del gruppo selezionato per nome, con i gruppi prima delle connessioni.',
    'Customize groups and order the tree.': "Personalizza i gruppi e ordina l'albero.",
    'Groups': 'Gruppi', 'Order': 'Ordine', 'Move up': 'Sposta su', 'Move down': 'Sposta giù',
    'Sort alphabetically': 'Ordina alfabeticamente', 'Expand all groups': 'Espandi tutti i gruppi',
    'Collapse all groups': 'Comprimi tutti i gruppi', 'Group icon': 'Icona gruppo',
    'Group name color': 'Colore nome gruppo', 'Invalid group appearance.': 'Aspetto del gruppo non valido.',
    'Invalid group icon.': 'Icona del gruppo non valida.',
    'Color of this group name in the tree. Does not change connection or tab colors.': "Colore del nome di questo gruppo nell'albero. Non modifica i colori delle connessioni o delle schede.",
    'Move the selected item up within its group.': "Sposta l'elemento selezionato verso l'alto nel suo gruppo.",
    'Move the selected item down within its group.': "Sposta l'elemento selezionato verso il basso nel suo gruppo.",
    'Sort this level by name, with groups before connections.': 'Ordina questo livello per nome, con i gruppi prima delle connessioni.',
    'Expand every group in the connection tree.': "Espandi tutti i gruppi nell'albero delle connessioni.",
    'Collapse every group in the connection tree.': "Comprimi tutti i gruppi nell'albero delle connessioni.",
    'Unable to save tree ordering.': "Impossibile salvare l'ordine dell'albero.",
    'Unable to save tree view state.': "Impossibile salvare lo stato dell'albero.",
    'The ordering destination no longer exists in this group.': 'La destinazione di ordinamento non esiste più in questo gruppo.',
    'Tree item no longer exists.': "L'elemento dell'albero non esiste più."
})


ITALIAN.update({
    'Shift': 'Maiusc',
    'File': 'File', 'Session': 'Sessione', 'View': 'Visualizza', 'Help': 'Aiuto',
    'About': 'Informazioni', 'About UniRCm': 'Informazioni su UniRCm', 'Version': 'Versione',
    'License': 'Licenza', 'Email': 'Email', 'Website': 'Sito web',
    'New local terminal': 'Nuovo terminale locale',
    'Local terminal': 'Terminale locale',
    'Open an interactive shell on this computer.': 'Apri una shell interattiva su questo computer.',
    'Local': 'Locale', 'Remote': 'Remoto',
    'Local profiles': 'Profili locali',
    'Show or hide the local terminal profiles in the connections panel.': 'Mostra o nascondi i profili dei terminali locali nel pannello delle connessioni.',
    'Add local profile': 'Aggiungi profilo locale',
    'Edit local profile': 'Modifica profilo locale',
    'Delete local profile': 'Elimina profilo locale',
    'Delete this local terminal profile?': 'Eliminare questo profilo del terminale locale?',
    'Open local terminal': 'Apri terminale locale',
    'Local terminal profile': 'Profilo del terminale locale',
    'Working directory': 'Directory di lavoro',
    'Startup commands': 'Comandi di avvio',
    'Commands to run in the interactive shell when opened': 'Comandi da eseguire nella shell interattiva all’apertura',
    'Save a local terminal with a working directory and startup commands.': 'Salva un terminale locale con directory di lavoro e comandi di avvio.',
    'Open this local terminal or drag it onto an empty workspace pane.': 'Apri questo terminale locale o trascinalo in un riquadro vuoto.',
    'Enter a profile name and valid directory and commands.': 'Inserisci il nome del profilo, una directory e comandi validi.',
    'A local terminal profile already uses this name.': 'Un profilo del terminale locale usa già questo nome.',
    'Unable to save the local terminal profile.': 'Impossibile salvare il profilo del terminale locale.',
    'Unable to start local terminal': 'Impossibile avviare il terminale locale',
    'Time since the local shell started': 'Tempo trascorso dall’avvio della shell locale',
    'Exit': 'Esci', 'Disconnect': 'Disconnetti', 'Close tab': 'Chiudi scheda',
    'Find connection': 'Cerca connessione', 'Toolbar': 'Barra degli strumenti', 'Status bar': 'Barra di stato',
    'Show or hide the connection toolbar.': 'Mostra o nascondi la barra degli strumenti delle connessioni.',
    'Show or hide the current session status.': 'Mostra o nascondi lo stato della sessione attuale.',
    'Create and open a separate encrypted configuration database.': 'Crea e apri un database di configurazione cifrato separato.',
    'Disconnect the current session and keep its terminal tab.': 'Disconnetti la sessione attuale mantenendo la scheda del terminale.',
    'Reconnect the stopped session using its current saved connection settings.': 'Riconnetti la sessione terminata usando le impostazioni salvate attuali.',
    'Close the current tab and disconnect its session.': 'Chiudi la scheda attuale e disconnetti la sessione.',
    'Exit UniRCm, disconnecting active sessions after confirmation.': 'Esci da UniRCm, disconnettendo le sessioni attive dopo conferma.',
    'Session disconnected.': 'Sessione disconnessa.',
    'SSH and Telnet connection manager with an embedded terminal and encrypted SQLCipher configuration.': 'Gestore di connessioni SSH e Telnet con terminale integrato e configurazione cifrata tramite SQLCipher.',
    'UniRCm help': 'Guida di UniRCm', 'Groups and ordering': 'Gruppi e ordinamento',
    'Sessions and terminal': 'Sessioni e terminale', 'Telnet login': 'Accesso Telnet',
    'Database and settings': 'Database e impostazioni',
    'Use File > New connection to create an SSH or Telnet connection. Select an existing connection and use Edit to change, move, duplicate or delete it.': 'Usa File > Nuova connessione per creare una connessione SSH o Telnet. Seleziona una connessione esistente e usa Modifica per modificarla, spostarla, duplicarla o eliminarla.',
    'Double-click a connection or use Session > Connect to open its terminal. Each connection uses an independent tab.': 'Fai doppio clic su una connessione oppure usa Sessione > Connetti per aprire il terminale. Ogni connessione usa una scheda indipendente.',
    'File > New group creates a group at the root; when a group or one of its connections is selected, New subgroup creates a subgroup there.': 'File > Nuovo gruppo crea un gruppo alla radice; quando è selezionato un gruppo o una sua connessione, Nuovo sottogruppo crea un sottogruppo al suo interno.',
    'Right-click the tree for group properties and Order. Drag above or below an item to reorder it, or onto a group to move it inside. Ctrl+Up/Down reorders only while the tree has focus.': "Fai clic destro nell'albero per le proprietà dei gruppi e il menu Ordine. Trascina sopra o sotto un elemento per riordinarlo, oppure su un gruppo per spostarlo al suo interno. Ctrl+Su/Giù riordina solo quando l'albero ha il focus.",
    'Group properties control the group icon and name color, inherited credentials, SSH defaults and terminal appearance. Connections can override inherited settings.': "Le proprietà del gruppo controllano icona, colore del nome, credenziali ereditate, valori predefiniti SSH e aspetto del terminale. Le connessioni possono personalizzare le impostazioni ereditate.",
    'Session > Disconnect stops the current session but keeps its terminal. Reconnect opens it again using the saved connection settings. Close tab disconnects and removes it.': 'Sessione > Disconnetti termina la sessione attuale mantenendo il terminale. Riconnetti la riapre usando le impostazioni salvate. Chiudi scheda disconnette e rimuove il terminale.',
    'Ctrl+Shift+C copies selected text; Ctrl+Shift+V pastes. Hold Shift to select locally when a remote program captures the mouse. Ctrl+mouse wheel changes font size.': 'Ctrl+Maiusc+C copia il testo selezionato; Ctrl+Maiusc+V incolla. Tieni premuto Maiusc per selezionare localmente quando un programma remoto cattura il mouse. Ctrl+rotella modifica la dimensione del carattere.',
    'Ctrl+N, Ctrl+O, Ctrl+F and F1 are local shortcuts only while the tree or search field has focus. Ordinary terminal control keys remain available to the remote program.': "Ctrl+N, Ctrl+O, Ctrl+F e F1 sono scorciatoie locali solo quando l'albero o il campo di ricerca hanno il focus. I normali tasti di controllo del terminale restano disponibili al programma remoto.",
    'Telnet is unencrypted. Manual login sends no stored credentials automatically. In the Telnet tab, explicitly choose password-only or username/password login to send stored credentials at their prompts.': "Telnet non è cifrato. L'accesso manuale non invia automaticamente credenziali salvate. Nella scheda Telnet scegli esplicitamente l'accesso con sola password o con nome utente e password per inviare le credenziali ai rispettivi prompt.",
    'Username prompt and Password prompt accept literal text such as login: and password:. Matching ignores letter case. Leave blank for automatic detection; each field is sent once and retries remain manual.': 'Prompt nome utente e Prompt password accettano testo letterale come login: e password:. Il confronto ignora maiuscole e minuscole. Lascia vuoto per il riconoscimento automatico; ogni campo viene inviato una sola volta e i tentativi successivi restano manuali.',
    'Changes are saved automatically to the encrypted database. File > Open database switches databases; File > New database creates a separate archive.': 'Le modifiche vengono salvate automaticamente nel database cifrato. File > Apri database cambia database; File > Nuovo database crea un archivio separato.',
    'Edit > Credentials manages shared credentials. Edit > Settings selects English/Italian, inactivity lock, archive description and master-password change. The archive description is public.': 'Modifica > Credenziali gestisce le credenziali condivise. Modifica > Impostazioni permette di scegliere Inglese/Italiano, blocco per inattività, descrizione archivio e cambio della password principale. La descrizione è pubblica.',
    'File > Lock disconnects all sessions and requires the master password again. Exit asks for confirmation when sessions are active. A forgotten master password cannot be recovered.': 'File > Blocca disconnette tutte le sessioni e richiede di nuovo la password principale. Esci chiede conferma quando ci sono sessioni attive. Una password principale dimenticata non può essere recuperata.',
    'To back up a database, copy its .uni file elsewhere. Open that copy with Open database when needed.': 'Per fare una copia di sicurezza del database, copia il file .uni altrove. Quando serve, apri la copia con Apri database.'
})


ITALIAN.update({
    'The icon bar below the tree provides Add, Delete, Move up/down, Cut, Copy and Paste. Copy duplicates a connection; Cut moves a group or connection. Select a destination before pasting. Escape in the tree cancels the pending transfer.': "La barra a icone sotto l'albero offre Aggiungi, Elimina, Sposta su/giù, Taglia, Copia e Incolla. Copia duplica una connessione; Taglia sposta un gruppo o una connessione. Seleziona una destinazione prima di incollare. Esc nell'albero annulla l'operazione in attesa.",
    'Add': 'Aggiungi', 'Cut': 'Taglia', 'Paste failed': 'Incolla non riuscito',
    'Add a connection or a group here.': 'Aggiungi qui una connessione o un gruppo.',
    'Cut the selected group or connection, then select a destination and paste.': 'Taglia il gruppo o la connessione selezionata, poi seleziona una destinazione e incolla.',
    'Copy the selected connection.': 'Copia la connessione selezionata.',
    'Paste into the selected group, after the selected connection, or at root on empty space.': 'Incolla nel gruppo selezionato, dopo la connessione selezionata o alla radice sullo spazio vuoto.',
    'Unable to paste into the encrypted database.': 'Impossibile incollare nel database cifrato.'
})


ITALIAN.update({
    'Download folder': 'Cartella download',
    'Close pane': 'Chiudi pannello',
    'Connection failed': 'Connessione fallita',
})

ITALIAN.update({
    'Choose icon': 'Scegli icona',
    'Padlock': 'Lucchetto',
    'Search icons…': 'Cerca icone…',
    'Available icons': 'Icone disponibili',
    'Choose an icon from the library.': 'Scegli un’icona dalla libreria.',
    'Cloud upload': 'Caricamento cloud',
    'Cloud download': 'Download cloud',
    'Storage': 'Archiviazione',
    'Processor': 'Processore',
    'Memory': 'Memoria',
    'Circuit board': 'Scheda elettronica',
    'Container': 'Contenitore',
    'Cluster': 'Cluster',
    'Virtual machines': 'Macchine virtuali',
    'World': 'Mondo',
    'Key': 'Chiave',
    'Security': 'Sicurezza',
    'Security alert': 'Avviso sicurezza',
    'Authentication': 'Autenticazione',
    'Cable': 'Cavo',
    'Radio': 'Radio',
    'Satellite': 'Satellite',
    'Antenna': 'Antenna',
    'Printer': 'Stampante',
    'Phone': 'Telefono',
    'Camera': 'Fotocamera',
    'Surveillance': 'Videosorveglianza',
    'Workstation': 'Postazione',
    'Managed server': 'Server gestito',
    'Server alert': 'Avviso server',
    'Database backup': 'Backup database',
    'Database service': 'Servizio database',
    'Shared folder': 'Cartella condivisa',
    'Archive': 'Archivio',
    'Office': 'Ufficio',
    'Home': 'Casa',
    'Factory': 'Fabbrica',
    'Warehouse': 'Magazzino',
    'Code': 'Codice',
    'Git branch': 'Ramo Git',
    'Git fork': 'Fork Git',
    'Tools': 'Strumenti',
    'Monitoring': 'Monitoraggio',
    'Performance': 'Prestazioni',
    'Statistics': 'Statistiche',
    'Debugging': 'Debug',
    'Automation': 'Automazione',
    'Mail': 'Posta',
    'Users': 'Utenti',
    'User': 'Utente',
    'Service': 'Servizio',
    'Plug': 'Spina',
    'Power': 'Accensione',
    'Energy': 'Energia',
    'Battery': 'Batteria',
})


def translation(text, language):
    return ITALIAN.get(text.replace('&', ''), text) if language == 'it' else text


ITALIAN.update({
    'SSH advanced': 'SSH avanzato',
    'Advanced options source': 'Origine opzioni avanzate',
    'Jump host': 'Host intermedio',
    'Keepalive interval (seconds)': 'Intervallo keepalive (secondi)',
    'Unanswered keepalives': 'Keepalive senza risposta',
    'Use configured identities only': 'Usa solo le identità configurate',
    'IP version': 'Versione IP',
    'Compression': 'Compressione',
    'OpenSSH configuration': 'Configurazione OpenSSH',
    'Automatic': 'Automatico',
    'Optional [user@]host[:port]; separate multiple jump hosts with commas. Blank uses OpenSSH configuration.': 'Facoltativo: [utente@]host[:porta]; separa più host con virgole. Vuoto usa la configurazione OpenSSH.',
    'Send a keepalive after this many seconds without server data. Zero disables keepalives.': 'Invia un keepalive dopo questi secondi senza dati dal server. Zero disabilita i keepalive.',
    'Disconnect after this many unanswered keepalives.': 'Disconnetti dopo questo numero di keepalive senza risposta.',
    'Restrict authentication to configured identities instead of trying every agent key.': 'Limita l’autenticazione alle identità configurate senza provare tutte le chiavi dell’agent.',
    'Choose automatic addressing, IPv4 or IPv6.': 'Scegli indirizzamento automatico, IPv4 o IPv6.',
    'Compression can help on slow links; it is usually unnecessary on fast networks.': 'La compressione può aiutare sui collegamenti lenti; di solito non serve sulle reti veloci.',
})


ITALIAN.update({'Additional SSH options': 'Opzioni SSH aggiuntive', 'Use -o Name=value, separated by spaces or newlines. Examples:\n-o HostKeyAlgorithms=+ssh-rsa\n-o KexAlgorithms=+diffie-hellman-group14-sha1\n-o PubkeyAcceptedAlgorithms=+ssh-rsa\nEnable legacy algorithms only when required by this server. The + adds to modern defaults.\nSupported: KexAlgorithms, HostKeyAlgorithms, PubkeyAcceptedAlgorithms, Ciphers, MACs, RekeyLimit, IPQoS, TCPKeepAlive, NumberOfPasswordPrompts, FingerprintHash.\nPasswords, commands, configuration files and session-management overrides are not accepted.': 'Usa -o Nome=valore, separando le opzioni con spazi o righe nuove. Esempi:\n-o HostKeyAlgorithms=+ssh-rsa\n-o KexAlgorithms=+diffie-hellman-group14-sha1\n-o PubkeyAcceptedAlgorithms=+ssh-rsa\nAbilita gli algoritmi obsoleti solo se richiesti da questo server. Il + li aggiunge ai valori moderni.\nSupportati: KexAlgorithms, HostKeyAlgorithms, PubkeyAcceptedAlgorithms, Ciphers, MACs, RekeyLimit, IPQoS, TCPKeepAlive, NumberOfPasswordPrompts, FingerprintHash.\nNon sono accettati password, comandi, file di configurazione o modifiche alla gestione della sessione.'})


ITALIAN.update({
    'Invalid additional SSH options.': 'Opzioni SSH aggiuntive non valide.',
    'Invalid quoting in additional SSH options.': 'Virgolette non valide nelle opzioni SSH aggiuntive.',
    'Use -o Name=value for additional SSH options.': 'Usa -o Nome=valore per le opzioni SSH aggiuntive.',
    'Unsupported additional SSH option. Use the dedicated fields for connection settings.': 'Opzione SSH aggiuntiva non supportata. Usa i campi dedicati per le impostazioni di connessione.',
    'Duplicate additional SSH option.': 'Opzione SSH aggiuntiva duplicata.',
    'Invalid additional SSH option value.': 'Valore non valido per un’opzione SSH aggiuntiva.',
})




ITALIAN.update({'Connection port. Editing the SSH port overrides the inherited group value.': 'Porta del collegamento. Modificare la porta SSH sostituisce il valore ereditato dal gruppo.'})


ITALIAN.update({'Stored passwords are not sent in this mode. Enter the password in the remote client or terminal.': 'Le password salvate non vengono inviate in questa modalità. Inserisci la password nel client remoto o nel terminale.'})


ITALIAN.update({
    'Manual Telnet login does not use stored credentials.': 'Il login Telnet manuale non usa le credenziali salvate.',
    'Stored in the encrypted database and sent once at the Telnet password prompt. Telnet transmits it without encryption.': 'Salvata nel database cifrato e inviata una sola volta al prompt password Telnet. Telnet la trasmette senza cifratura.',
    'No username configured': 'Nessun nome utente configurato',
})


ITALIAN.update({
    'Connection tree': 'Albero delle connessioni',
    'Drag to resize; double-click to hide the connections panel.': 'Trascina per ridimensionare; fai doppio clic per nascondere il pannello delle connessioni.',
    'Show or hide the connections panel, including search and tree tools.': 'Mostra o nasconde il pannello delle connessioni, inclusi ricerca e comandi dell’albero.',
    'No databases in the list. Open a file or create a new database.': 'Nessun database in elenco. Apri un file o crea un nuovo database.',
    'No shared credentials yet. Use New credential to create one.': 'Nessuna credenziale condivisa. Usa Nuova credenziale per crearne una.',
})


class ItalianTranslator(QTranslator):
    def isEmpty(self):
        return False

    def translate(self, context, sourceText, disambiguation=None, n=-1):
        return ITALIAN.get(sourceText.replace('&', ''), sourceText)


class InterfaceTranslations(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.language = 'en'
        self.reverse = {value: key for key, value in ITALIAN.items()}

    def apply(self, root):
        objects = [root, *root.findChildren(QObject)]
        for obj in objects:
            properties = ['toolTip', 'accessibleName']
            if isinstance(obj, QPushButton):
                if obj.icon().isNull():
                    obj.setIcon(QIcon.fromTheme('preferences-system', obj.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)))
                if not obj.toolTip():
                    obj.setToolTip(obj.text().replace('&', ''))
            if isinstance(obj, (QAbstractButton, QLabel, QAction)):
                properties.append('text')
            if isinstance(obj, (QDialog, QMainWindow)):
                properties.append('windowTitle')
            if isinstance(obj, QLineEdit):
                properties.append('placeholderText')
            if isinstance(obj, QTreeWidget):
                header = obj.headerItem()
                for column in range(header.columnCount()):
                    value = header.text(column)
                    source = value if value in ITALIAN else self.reverse.get(value)
                    if source:
                        header.setText(column, translation(source, self.language))
            for prop in properties:
                value = obj.property(prop)
                if not isinstance(value, str):
                    continue
                source = value.replace('&', '')
                if source not in ITALIAN:
                    source = self.reverse.get(value)
                if source:
                    obj.setProperty(prop, translation(source, self.language))

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show and isinstance(obj, (QDialog, QMainWindow, QMenu)):
            self.apply(obj)
        return False


def set_language(language):
    app = QApplication.instance()
    previous = getattr(app, '_unircm_translator', None)
    if previous:
        app.removeTranslator(previous)
        previous.deleteLater()
    app._unircm_translator = ItalianTranslator(app) if language == 'it' else None
    if app._unircm_translator:
        app.installTranslator(app._unircm_translator)
    if not hasattr(app, '_unircm_ui_translations'):
        app._unircm_ui_translations = InterfaceTranslations(app)
        app.installEventFilter(app._unircm_ui_translations)
    app._unircm_ui_translations.language = language
    for window in app.topLevelWidgets():
        app._unircm_ui_translations.apply(window)
