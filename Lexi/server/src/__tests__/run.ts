// Loads every *.test.ts in this folder; each file registers its tests with node:test.
import { readdirSync } from 'fs';
import { join } from 'path';

readdirSync(__dirname)
    .filter((f) => f.endsWith('.test.ts'))
    .forEach((f) => require(join(__dirname, f)));
