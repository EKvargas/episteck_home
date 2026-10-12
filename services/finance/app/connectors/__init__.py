import logging

# httpx logs every request URL at INFO. For connectors that URL can carry a secret (the
# SimpleFIN claim token, EB authorization codes), so the library loggers are held at
# WARNING for the whole process the moment any connector is imported.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)
