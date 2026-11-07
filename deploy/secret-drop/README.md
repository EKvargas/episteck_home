# Secret drop

A write-only drop box the owner uses to send a secret (a bot token, a password) from the phone to `episteck-node1`. The secret never passes through a chat, an agent, the laptop or git. Bitwarden stays the vault for secrets that can't be regenerated. The drop only delivers them.

Live since 2026-11-07. The first slot is the Telegram bot token for Hermes `home-agent` (Olin).

## How it works

- `/usr/local/sbin/secret-drop` (`root:root 0755`) is this folder's `secret-drop`.
- One SSH key on the owner's phone (Termius, key `secret-drop-phone`) is locked to that script in `~episteck/.ssh/authorized_keys`:

  ```
  restrict,pty,command="sudo -n /usr/local/sbin/secret-drop" ssh-ed25519 AAAA... secret-drop-phone
  ```

  `restrict` turns off forwarding, agent and X11. `pty` brings back only the terminal, which the hidden prompt needs. `command=` ignores whatever the client asks to run. The key opens no shell and runs nothing else.
- The script shows the slots, asks for a number and then reads the secret through a hidden prompt (5 min timeout). It refuses a slot that is already filled and checks the value against that slot's format. Before writing, it backs up the target as `<target>.bak-secret-drop-<UTC stamp>`.
  - `env` slots append `KEY=value` to an existing file; `file` slots create a new file.
  - Either way the target ends up mode 600, owned by the slot owner.
- It never prints, logs or reads back a value. The journal gets only `secret-drop: stored slot=<name> by <user>`.

## Use it (owner, phone)

1. Termius → host `episteck-node1 (secret drop)`: `91.98.132.9`, user `episteck`, key `secret-drop-phone`.
2. Pick the slot number and paste the secret at the hidden prompt.
3. Tell Claude it is done. Claude checks the journal line and the target's mode, and restarts the consumer if needed.

## Add a slot (Claude prepares, owner names the change)

Add one line to `SLOTS`:

```
name|kind|target|owner|ENV_KEY|^format$|label
```

- `kind` is `env` (append `ENV_KEY=value` to an existing file) or `file` (create the target; leave `ENV_KEY` empty).
- The format regex must be anchored with `^` and `$`.

Run `python -m pytest deploy/secret-drop/tests -q`, merge, then install:

```bash
sudo install -m 0755 -o root -g root deploy/secret-drop/secret-drop /usr/local/sbin/secret-drop
sudo bash -n /usr/local/sbin/secret-drop
printf '9\n' | sudo /usr/local/sbin/secret-drop   # wrong number: must store nothing
```

## Rotate a secret

The drop never overwrites. Claude clears the old value first with a backup: removes the `KEY=` line or moves the file to `.bak-rotate-<stamp>`. The owner then drops the new value, and Claude restarts the consumer.

## Roll back

- A stored value: restore `<target>.bak-secret-drop-<stamp>` and restart the consumer.
- The whole drop: delete the `secret-drop-phone` line from `~episteck/.ssh/authorized_keys` (a backup is at `authorized_keys.bak-secret-drop`) and remove `/usr/local/sbin/secret-drop`.
