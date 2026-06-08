import { useCallback, useEffect, useState } from 'react';
import { deleteUser, fetchUsers } from '../api/userApi.js';

export default function UserListPage() {
  const [users, setUsers] = useState([]);
  const [search, setSearch] = useState('');
  const [role, setRole] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await fetchUsers({ search, role });
      setUsers(data);
    } catch (e) {
      setError(e.message || '请求失败');
    } finally {
      setLoading(false);
    }
  }, [search, role]);

  useEffect(() => {
    load();
  }, [load]);

  const handleDelete = async (id) => {
    try {
      await deleteUser(id);
      await load();
    } catch (e) {
      setError(e.message || '删除失败');
    }
  };

  return (
    <div>
      <h1>用户列表</h1>
      {error && <div role="alert">{error}</div>}
      <div>
        <label htmlFor="search">搜索</label>
        <input
          id="search"
          aria-label="搜索用户名"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <label htmlFor="role">角色</label>
        <select id="role" aria-label="角色筛选" value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="">全部</option>
          <option value="admin">admin</option>
          <option value="user">user</option>
        </select>
      </div>
      {loading ? (
        <p>加载中...</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>用户名</th>
              <th>邮箱</th>
              <th>角色</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>{u.username}</td>
                <td>{u.email}</td>
                <td>{u.role}</td>
                <td>
                  <button type="button" onClick={() => handleDelete(u.id)}>
                    删除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
