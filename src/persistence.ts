import { mkdir, readdir, readFile, writeFile, unlink } from 'node:fs/promises';
import { join } from 'node:path';
import { existsSync } from 'node:fs';

import { type SavedLevelState } from './game-engine.js';

export interface PersistedSession {
  id: string;
  levelId: string;
  tokenOrderMode: 'forward' | 'reverse';
  levelStates: Record<string, SavedLevelState>;
  version: number;
  createdAt: string;
  updatedAt: string;
}

let sessionsDir = 'sessions';

export function setSessionsDirectory(dir: string): void {
  sessionsDir = dir;
}

export function getSessionsDirectory(): string {
  return sessionsDir;
}

async function ensureSessionsDir(): Promise<void> {
  if (!existsSync(sessionsDir)) {
    await mkdir(sessionsDir, { recursive: true });
  }
}

function getSessionPath(id: string): string {
  return join(sessionsDir, `${id}.json`);
}

function generateSessionId(): string {
  const timestamp = Date.now().toString(36);
  const random = Math.random().toString(36).slice(2, 8);
  return `sess_${timestamp}_${random}`;
}

export async function listSessions(): Promise<PersistedSession[]> {
  await ensureSessionsDir();

  const files = await readdir(sessionsDir);
  const sessions: PersistedSession[] = [];

  for (const file of files) {
    if (!file.endsWith('.json')) continue;

    try {
      const content = await readFile(join(sessionsDir, file), 'utf-8');
      const session = JSON.parse(content) as PersistedSession;
      sessions.push(session);
    } catch {
      console.warn(`Skipping invalid session file: ${file}`);
    }
  }

  sessions.sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());

  return sessions;
}

export async function loadSession(id: string): Promise<PersistedSession | null> {
  await ensureSessionsDir();

  const path = getSessionPath(id);
  try {
    const content = await readFile(path, 'utf-8');
    return JSON.parse(content) as PersistedSession;
  } catch {
    return null;
  }
}

export async function saveSession(
  data: Omit<PersistedSession, 'id' | 'createdAt' | 'updatedAt'> & { id?: string }
): Promise<PersistedSession> {
  await ensureSessionsDir();

  const now = new Date().toISOString();
  const id = data.id ?? generateSessionId();
  const existing = data.id ? await loadSession(data.id) : null;

  if (existing && existing.version !== data.version) {
    throw new Error('Version mismatch - session was modified by another request');
  }

  const session: PersistedSession = {
    id,
    levelId: data.levelId,
    tokenOrderMode: data.tokenOrderMode,
    levelStates: data.levelStates,
    version: (existing?.version ?? 0) + 1,
    createdAt: existing?.createdAt ?? now,
    updatedAt: now,
  };

  const path = getSessionPath(id);
  await writeFile(path, JSON.stringify(session, null, 2), 'utf-8');

  return session;
}

export async function deleteSession(id: string): Promise<boolean> {
  await ensureSessionsDir();

  const path = getSessionPath(id);
  try {
    await unlink(path);
    return true;
  } catch {
    return false;
  }
}
