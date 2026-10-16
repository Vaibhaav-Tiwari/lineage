#!/usr/bin/env bash
# Reproduce: FalkorDB's documented read-only ACL pattern (%R~) refuses GRAPH.RO_QUERY.
# Runs against a fresh, throwaway container and removes it afterwards.
#   bash docs/upstream/repro/acl_readonly.sh | tee docs/upstream/evidence/acl_readonly.txt
set -u
IMG="${IMG:-falkordb/falkordb:6.0.2}"; NAME=acl-repro; PORT=6393
r() { docker exec "$NAME" redis-cli "$@"; }
as() { local u=$1 p=$2; shift 2; docker exec "$NAME" redis-cli --no-auth-warning --user "$u" --pass "$p" "$@"; }
say() { printf '\n# %s\n' "$*"; }
cmd() { printf '$ %s\n' "$*"; }

docker rm -f "$NAME" >/dev/null 2>&1
docker run -d --name "$NAME" -p "127.0.0.1:$PORT:6379" "$IMG" >/dev/null
for _ in $(seq 1 30); do r PING 2>/dev/null | grep -q PONG && break; sleep 1; done

say "Environment ($(date -u +%Y-%m-%dT%H:%M:%SZ))"
echo "image: $IMG"
r INFO server | grep -E '^redis_version' | tr -d '\r'
echo "graph module: $(r MODULE LIST | sed -n '/^graph$/{n;n;p;}')"

say "A graph to read"
cmd 'GRAPH.QUERY app2:users "CREATE (:U)"'
r GRAPH.QUERY app2:users "CREATE (:U)" | head -1

say "Docs example 1 (docs.falkordb.com/commands/acl): read-only user"
cmd 'ACL SETUSER reader_doc on >pass +GRAPH.RO_QUERY %R~*'
r ACL SETUSER reader_doc on '>pass' +GRAPH.RO_QUERY '%R~*'
cmd '(as reader_doc) GRAPH.RO_QUERY app2:users "MATCH (n) RETURN count(n)"'
as reader_doc pass GRAPH.RO_QUERY app2:users "MATCH (n) RETURN count(n)" 2>&1 | head -2

say "Docs example 2: full access to app1:*, read-only access to app2:*"
cmd 'ACL SETUSER rw_doc on >pass +@all ~app1:* %R~app2:*'
r ACL SETUSER rw_doc on '>pass' +@all '~app1:*' '%R~app2:*'
cmd '(as rw_doc) GRAPH.RO_QUERY app2:users "MATCH (n) RETURN count(n)"'
as rw_doc pass GRAPH.RO_QUERY app2:users "MATCH (n) RETURN count(n)" 2>&1 | head -2

say "Why: the ACL log says the key was refused"
cmd 'ACL LOG 1'
r ACL LOG 1 | paste - - | grep -E '^(reason|context|object|username)' | tr '\t' ' '

say "Workaround: a Redis ACL selector that grants only GRAPH.RO_QUERY on the read-only pattern"
cmd 'ACL SETUSER agent on >pass resetkeys -@all +@connection +INFO ~app1:* +GRAPH.QUERY +GRAPH.RO_QUERY (~app2:* +GRAPH.RO_QUERY)'
r ACL SETUSER agent on '>pass' resetkeys -@all +@connection +INFO '~app1:*' +GRAPH.QUERY +GRAPH.RO_QUERY '(~app2:* +GRAPH.RO_QUERY)'
cmd '(as agent) GRAPH.RO_QUERY app2:users "MATCH (n) RETURN count(n)"   # read: allowed'
as agent pass GRAPH.RO_QUERY app2:users "MATCH (n) RETURN count(n)" 2>&1 | head -2
cmd '(as agent) GRAPH.QUERY app2:users "CREATE (:Hacked)"             # write: refused'
as agent pass GRAPH.QUERY app2:users "CREATE (:Hacked)" 2>&1 | head -1
cmd '(as agent) GRAPH.QUERY app1:own "CREATE (:Mine)"                 # own graph: allowed'
as agent pass GRAPH.QUERY app1:own "CREATE (:Mine)" 2>&1 | head -1
cmd 'GRAPH.RO_QUERY app2:users "MATCH (h:Hacked) RETURN count(h)"     # nothing was written'
r GRAPH.RO_QUERY app2:users "MATCH (h:Hacked) RETURN count(h)" | sed -n 2p

docker rm -f "$NAME" >/dev/null
say "Done: throwaway container removed"
