#!/bin/sh
set -e
npx prisma db push
exec node dist/main.js
