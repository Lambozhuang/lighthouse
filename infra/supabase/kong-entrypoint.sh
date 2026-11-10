#!/bin/sh
# Entrypoint of the kong container: write the declarative config with the secrets filled in,
# then start Kong.
#
# kong.yml is committed with $NAME placeholders. Kong does not expand environment variables in
# that file itself, so this replaces every $NAME that is set in the environment and leaves the
# rest alone. (awk rather than a shell `eval`, which would strip the YAML quoting. Taken from
# the official Supabase kong-entrypoint.sh.)
set -eu

awk '{
  result = ""
  rest = $0
  while (match(rest, /\$[A-Za-z_][A-Za-z_0-9]*/)) {
    name = substr(rest, RSTART + 1, RLENGTH - 1)
    if (name in ENVIRON) {
      result = result substr(rest, 1, RSTART - 1) ENVIRON[name]
    } else {
      result = result substr(rest, 1, RSTART + RLENGTH - 1)
    }
    rest = substr(rest, RSTART + RLENGTH)
  }
  print result rest
}' /home/kong/kong.template.yml > "$KONG_DECLARATIVE_CONFIG"

exec /entrypoint.sh kong docker-start
