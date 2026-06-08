import { http, HttpResponse } from 'msw';

const users = [
  { id: '1', username: 'alice', email: 'alice@example.com', role: 'admin' },
  { id: '2', username: 'bob', email: 'bob@example.com', role: 'user' },
  { id: '3', username: 'carol', email: 'carol@example.com', role: 'user' },
];

export const handlers = [
  http.get('/api/users', ({ request }) => {
    const url = new URL(request.url);
    const search = url.searchParams.get('search') || '';
    const role = url.searchParams.get('role') || '';
    let result = [...users];
    if (search) {
      result = result.filter((u) => u.username.toLowerCase().includes(search.toLowerCase()));
    }
    if (role) {
      result = result.filter((u) => u.role === role);
    }
    return HttpResponse.json(result);
  }),
  http.delete('/api/users/:id', ({ params }) => {
    const idx = users.findIndex((u) => u.id === params.id);
    if (idx === -1) {
      return HttpResponse.json({ message: 'not found' }, { status: 404 });
    }
    users.splice(idx, 1);
    return HttpResponse.json({ success: true });
  }),
];
