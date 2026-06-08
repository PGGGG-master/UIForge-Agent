export async function fetchUsers(params = {}) {
  const query = new URLSearchParams();
  if (params.search) query.set('search', params.search);
  if (params.role) query.set('role', params.role);
  const qs = query.toString();
  const url = qs ? `/api/users?${qs}` : '/api/users';
  const res = await fetch(url);
  if (!res.ok) throw new Error('加载用户失败');
  return res.json();
}

export async function deleteUser(id) {
  const res = await fetch(`/api/users/${id}`, { method: 'DELETE' });
  if (!res.ok) throw new Error('删除用户失败');
  return res.json();
}
