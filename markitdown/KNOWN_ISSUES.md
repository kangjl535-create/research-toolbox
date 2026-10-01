# Known issues and validation limits

The system quick_validate.py rejects the unchanged upstream entry: Unexpected key(s) in SKILL.md frontmatter: compatibility. Allowed properties are: allowed-tools, description, license, metadata, name. This is an upstream/schema compatibility observation, not a new regression or a repaired issue. Host loading and behavior were not tested.
