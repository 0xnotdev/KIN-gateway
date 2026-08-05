# Backup and recovery
Stop the local node before copying `%USERPROFILE%\.kin\profiles\NAME`. The profile
contains the database, encrypted artifacts, preferences, and queued delivery
state, but the signing/encryption keys and provider credentials remain in the OS
keychain. Store the 12-word recovery phrase offline and separately from profile
backups.

To restore on a replacement computer, install the same or newer signed KIN
release, use `kin --profile NAME restore`, enter the phrase only at the protected
prompt, restore the profile backup, run migration if requested, and run `kin
doctor`. Reverify contact fingerprints out of band before resuming consequential
work. Test recovery periodically using a disposable machine/profile; never use a
production phrase in test logs or shell history.
