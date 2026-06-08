import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server } from '../src/mocks/server.js';
import { deleteUser, fetchUsers } from '../src/api/userApi.js';

describe('userApi', () => {
  it('fetchUsers returns list', async () => {
    const data = await fetchUsers();
    expect(data.length).toBeGreaterThan(0);
  });

  it('fetchUsers handles error', async () => {
    server.use(http.get('/api/users', () => HttpResponse.json({ message: 'err' }, { status: 500 })));
    await expect(fetchUsers()).rejects.toThrow('加载用户失败');
  });

  it('deleteUser succeeds', async () => {
    const before = await fetchUsers();
    const target = before[0];
    await deleteUser(target.id);
    const after = await fetchUsers();
    expect(after.find((u) => u.id === target.id)).toBeUndefined();
  });
});
