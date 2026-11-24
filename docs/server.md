# Run Monie on a Linux server

Use the same setup on a Linux machine or an EC2 Linux instance.

1. Put a fresh checkout in `/opt/monie` or in a directory of your choice.
2. Give an unprivileged Linux account ownership of the checkout, so Monie can write its state and logs.
3. As that account, follow the [README](../README.md) to create the virtual environment, install dependencies, and create `.env`.
4. Set `BROKER=PAPER` in `.env`. Set the file permissions with `chmod 600 .env`.
5. From the checkout, start Monie in the foreground.

   ```sh
   TZ=Asia/Kolkata .venv/bin/python main.py
   ```

6. Check that Monie starts in paper mode. Press `Ctrl+C` to stop it before you start the service.

The `TZ` setting gives the Monie process the market's local time.

## Start at boot with systemd

1. Copy [`monie.service`](../monie.service) to `/etc/systemd/system/monie.service`.
2. Set `User` to the account that owns the checkout.
3. Set `WorkingDirectory` and both paths in `ExecStart` to match the checkout and its virtual environment.
4. Reload systemd and enable the service.

   ```sh
   sudo systemctl daemon-reload
   sudo systemctl enable --now monie.service
   sudo systemctl status monie.service
   ```

5. Use `sudo journalctl -u monie.service -f` to read the service log.

To update an existing service, keep its checkout, `.env`, and runtime data.
Match the template to the installed paths and account before you replace the unit.
After you reload systemd, run `sudo systemctl restart monie.service` to apply the unit changes.
