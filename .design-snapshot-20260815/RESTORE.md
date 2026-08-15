# Rolling back the 2026-08-15 design pass

This repository is not under version control, so the files that pass touched
were copied here first, byte for byte, before anything changed.

To put them back:

    cd /Users/ovidiubistrian/work/personal/footbola
    cp -R .design-snapshot-20260815/apps    ./
    cp -R .design-snapshot-20260815/backend ./
    cp -R .design-snapshot-20260815/packages ./
    docker compose restart api public-web

Two files are new rather than changed, so restoring does not remove them —
delete them by hand if you want the previous layout exactly:

    apps/public-web/src/templates/club-feed.tsx
    apps/public-web/src/templates/newsletter.tsx
    apps/public-web/src/app/api/newsletter/route.ts
    backend/app/fans/
    apps/public-web/src/templates/section.tsx

The database changes from this pass (the demo club's crest) are additive and
harmless to leave in place.

A real answer to "prepare a rollback" is `git init` — one commit here would
make every future change reversible without copying files around. Worth doing
before the next design pass.
