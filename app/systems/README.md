# GMForge Systems

Rules-system modules live here.

Important:
`GMForge` must still function with no systems loaded at all.
The platform core is allowed to run in a fully generic mode with:
- `system_id = "none"`
- no addons
- no plugins
- only core storage, content, and context services enabled

Each system should follow the same broad structure:

```text
<system_id>/
├── system.json
├── README.md
├── addons/
│   └── <addon_id>/
│       ├── addon.json
│       └── README.md
├── content_types/
├── generation/
├── rules/
├── tools/
└── ui/
```

The internal details may differ by system, but the top-level shape should stay as consistent as possible across:
- `cypher`
- `mist_engine`
- `savage_worlds`
- `outgunned`
- `daggerheart`
