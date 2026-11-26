"""Network ingestion: UDP datagrams and TCP line streams carrying JSON detections.

Wire format (one of):

* a JSON object                       -> one detection
* a JSON array of objects             -> a batch
* newline-delimited JSON (TCP / UDP)  -> one detection per line


from __future__ import annotations

import 