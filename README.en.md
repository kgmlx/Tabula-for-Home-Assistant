German version: [README.md](README.md)

# Tabula for Home Assistant

Push invoices and bank statements from Home Assistant into [Tabula](https://docs.tabula.de/) - from automations, scripts, or manually.

## Setup

**HACS:** Add custom repository `https://github.com/kgmlx/Tabula-for-Home-Assistant` (category Integration), then install Tabula.

**Manual:**

1. Download the latest version from [Releases](https://github.com/kgmlx/Tabula-for-Home-Assistant/releases/latest) (`Source code` ZIP)
2. From the archive, copy the folder `custom_components/tabula` to `config/custom_components/tabula/`
3. Restart Home Assistant
4. Settings → Devices & services → Add integration → Tabula
5. Enter an API key from Tabula (Settings → API settings)

Tabula shows the key only once. Best to store it in a password manager right away.

After setup you get sensors for the company and the key. The actual work happens through services.

## Examples

### Single incoming invoice

PDF sits e.g. in `/config/www/` or in a media folder. Upload once and wait until Tabula is done:

```yaml
action: tabula.upload_document
data:
  path: /config/www/invoice-2026-0042.pdf
  document_type: supplier_invoice
  external_id: ERP-2026-0042
  poll: true
```

`external_id` prevents duplicate uploads if the automation fires again. Without it, Tabula still recognizes identical files by content.

Outgoing invoices: `customer_invoice`. Unsure? `auto` - except bank statements, which always need `bank_statement`.

### Watch a folder

New PDFs land in a folder (scanner, mail attachment, NAS sync). Folder Watcher or your own automation then calls `upload_document`. Relative paths start at the config directory:

```yaml
action: tabula.upload_document
data:
  path: www/inbox/{{ trigger.file }}
  document_type: auto
  poll: false
```

With `poll: false` the call returns immediately. Sensor **Last upload** and event `tabula_upload` show progress. Follow up later with:

```yaml
action: tabula.get_upload
data:
  upload_id: "{{ states.sensor.tabula_last_upload.attributes.upload_id }}"
  poll: true
```

(Entity ID may differ on your system - check Developer tools.)

### Multiple documents at once

ZIP with up to 100 files:

```yaml
action: tabula.upload_batch
data:
  path: /media/tabula/daily-stack.zip
  document_type: supplier_invoice
  poll: true
```

Sensor **Last batch** has counters for completed/failed. Event `tabula_batch` fires on each poll step.

### React to failures

```yaml
automation:
  - alias: Tabula upload failed
    triggers:
      - trigger: event
        event_type: tabula_upload
    conditions:
      - condition: template
        value_template: "{{ trigger.event.data.upload.status == 'failed' }}"
    actions:
      - action: notify.mobile_app_phone
        data:
          title: Tabula
          message: >
            {{ trigger.event.data.upload.fileName }}:
            {{ trigger.event.data.upload.error.message }}
```

### Key about to expire

Sensor **Key expires** works well for a reminder a few days ahead.

## Path notes

Only files under the HA config folder or a configured media directory work. Absolute paths outside that are rejected.

### Multiple companies

One Tabula integration entry in HA per company. Pass `config_entry_id` on service calls:

- **UI:** use the Config entry field - your Tabula companies appear in the list.
- **YAML:** Settings → Devices & services → Tabula → open the company. The browser address contains something like `config_entry=01JABC...` - use that value:

```yaml
action: tabula.upload_document
data:
  path: /config/www/invoice.pdf
  document_type: supplier_invoice
  config_entry_id: 01JABC...
```

API details: https://docs.tabula.de/
