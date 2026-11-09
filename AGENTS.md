# Source maintenance

- All successful delivery paths use utils.delivery.send_delivery_thanks only after the buyer's delivery succeeds; its persisted per-user order key prevents repeated follow-ups without changing purchase accounting.
- Visit Again shares the existing start handler so user restrictions, terms checks, and menu state reset stay consistent with /start.
- Offline tests run with a disposable DATA_DIR and mocked external services; never execute them against production data.
