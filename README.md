English version: [README.en.md](README.en.md)

# Tabula für Home Assistant

Rechnungen und Kontoauszüge aus Home Assistant nach [Tabula](https://docs.tabula.de/) schieben - per Automatisierung, Skript oder manuell.

## Einrichten

**HACS:** Custom Repository `https://github.com/kgmlx/Tabula-for-Home-Assistant` (Kategorie Integration), dann Tabula installieren.

**Manuell:**

1. Neueste Version unter [Releases](https://github.com/kgmlx/Tabula-for-Home-Assistant/releases/latest) herunterladen (`Source code` ZIP)
2. Daraus den Ordner `custom_components/tabula` nach `config/custom_components/tabula/` kopieren
3. Home Assistant neu starten
4. Einstellungen → Geräte & Dienste → Integration hinzufügen → Tabula
5. API-Schlüssel aus Tabula (Einstellungen → API-Einstellungen) eintragen

Den Schlüssel zeigt Tabula nur einmal. Am besten direkt in einem Passwortmanager ablegen.

Nach dem Einrichten erscheinen Sensoren zur Firma und zum Schlüssel. Die eigentliche Arbeit läuft über Services.

## Beispiele

### Einzelne Eingangsrechnung

PDF liegt z.B. unter `/config/www/` oder im Media-Ordner. Einmal hochladen und warten, bis Tabula fertig ist:

```yaml
action: tabula.upload_document
data:
  path: /config/www/Rechnung-2026-0042.pdf
  document_type: supplier_invoice
  external_id: ERP-2026-0042
  poll: true
```

`external_id` verhindert Doppel-Uploads, wenn die Automatisierung nochmal feuert. Ohne Angabe erkennt Tabula identische Dateien am Inhalt.

Ausgangsrechnungen: `customer_invoice`. Unklar? `auto` - außer bei Kontoauszügen, die brauchen immer `bank_statement`.

### Ordner überwachen

Neue PDFs landen in einem Ordner (Scanner, Mail-Anhang, NAS-Sync). Folder-Watcher oder eine eigene Automatisierung ruft dann `upload_document` auf. Relativer Pfad geht vom Config-Verzeichnis aus:

```yaml
action: tabula.upload_document
data:
  path: www/eingang/{{ trigger.file }}
  document_type: auto
  poll: false
```

Mit `poll: false` kehrt der Aufruf sofort zurück. Sensor **Letzter Upload** und Event `tabula_upload` zeigen den Fortschritt. Später nachziehen:

```yaml
action: tabula.get_upload
data:
  upload_id: "{{ states.sensor.tabula_letzter_upload.attributes.upload_id }}"
  poll: true
```

(Entity-ID kann bei dir anders heißen - im Developer-Tool nachschauen.)

### Mehrere Belege auf einmal

ZIP mit bis zu 100 Dateien:

```yaml
action: tabula.upload_batch
data:
  path: /media/tabula/tagesstapel.zip
  document_type: supplier_invoice
  poll: true
```

Im Sensor **Letzter Batch** stehen Zähler für completed/failed. Event `tabula_batch` kommt bei jedem Poll-Schritt.

### Auf Fehler reagieren

```yaml
automation:
  - alias: Tabula Upload fehlgeschlagen
    triggers:
      - trigger: event
        event_type: tabula_upload
    conditions:
      - condition: template
        value_template: "{{ trigger.event.data.upload.status == 'failed' }}"
    actions:
      - action: notify.mobile_app_telefon
        data:
          title: Tabula
          message: >
            {{ trigger.event.data.upload.fileName }}:
            {{ trigger.event.data.upload.error.message }}
```

### Schlüssel läuft ab

Sensor **Schlüssel gültig bis** eignet sich für eine Erinnerung ein paar Tage vorher.

## Hinweise zu Pfaden

Nur Dateien unter dem HA-Config-Ordner oder einem konfigurierten Media-Verzeichnis funktionieren. Absolute Pfade außerhalb davon werden abgelehnt.

### Mehrere Firmen

Pro Firma eine Tabula-Integration in HA. Bei Service-Aufrufen dann `config_entry_id` setzen:

- **UI:** Feld „Config-Eintrag“ - dort stehen deine Tabula-Firmen zur Auswahl.
- **YAML:** Einstellungen → Geräte & Dienste → Tabula → gewünschte Firma öffnen. In der Browser-Adresse steht etwas wie `config_entry=01JABC...` - diesen Wert verwenden:

```yaml
action: tabula.upload_document
data:
  path: /config/www/Rechnung.pdf
  document_type: supplier_invoice
  config_entry_id: 01JABC...
```

API-Details: https://docs.tabula.de/
