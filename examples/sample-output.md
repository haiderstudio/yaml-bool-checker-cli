```text
examples/bad-bool.yaml:3: unquoted value "on" reads as boolean true under YAML 1.1 (PyYAML); quote it if you mean the word "on"
examples/bad-bool.yaml:4: unquoted value "yes" reads as boolean true under YAML 1.1 (PyYAML); quote it if you mean the word "yes"
examples/bad-bool.yaml:5: unquoted value "off" reads as boolean false under YAML 1.1 (PyYAML); quote it if you mean the word "off"
examples/bad-bool.yaml:6: unquoted value "n" reads as boolean false under YAML 1.1 (PyYAML); quote it if you mean the word "n"
examples/bad-bool.yaml:7: unquoted value "YES" reads as boolean true under YAML 1.1 (PyYAML); quote it if you mean the word "YES"
examples/bad-norway.yaml:4: unquoted value "NO" reads as boolean false under YAML 1.1 (PyYAML); quote it if you mean the word "NO"
examples/bad-norway.yaml:5: unquoted value "no" reads as boolean false under YAML 1.1 (PyYAML); quote it if you mean the word "no"
examples/bad-norway.yaml:6: unquoted value "y" reads as boolean true under YAML 1.1 (PyYAML); quote it if you mean the word "y"
examples/configs/app.yaml:3: unquoted value "off" reads as boolean false under YAML 1.1 (PyYAML); quote it if you mean the word "off"
Checked 4 file(s), 9 problem(s) in 3 file(s).
```

Output of `sh examples/run-example.sh` — the checker on the whole
`examples/` folder. It exits 1, because the examples contain files
with unquoted boolean words on purpose; the script itself exits 0.
