#!/bin/sh
set -eu
python3 -c "import os, string, pathlib; \
  pathlib.Path('/config/buildarr.yml').write_text( \
  string.Template(pathlib.Path('/etc/buildarr/buildarr.yml.tmpl').read_text()).substitute(os.environ))"
exec buildarr daemon /config/buildarr.yml
