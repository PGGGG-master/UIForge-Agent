import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import UserListPage from '../src/pages/UserListPage.jsx';

describe('UserListPage', () => {
  it('renders user list', async () => {
    render(<UserListPage />);
    expect(await screen.findByText('alice')).toBeInTheDocument();
    expect(screen.getByText('bob')).toBeInTheDocument();
  });

  it('filters by search', async () => {
    const user = userEvent.setup();
    render(<UserListPage />);
    await screen.findByText('alice');
    await user.type(screen.getByLabelText('搜索用户名'), 'bob');
    await waitFor(() => {
      expect(screen.queryByText('alice')).not.toBeInTheDocument();
      expect(screen.getByText('bob')).toBeInTheDocument();
    });
  });

  it('filters by role', async () => {
    const user = userEvent.setup();
    render(<UserListPage />);
    await screen.findByText('alice');
    await user.selectOptions(screen.getByLabelText('角色筛选'), 'user');
    await waitFor(() => {
      expect(screen.queryByText('alice')).not.toBeInTheDocument();
      expect(screen.getByText('bob')).toBeInTheDocument();
    });
  });

  it('deletes a user', async () => {
    const user = userEvent.setup();
    render(<UserListPage />);
    await screen.findByText('carol');
    const deleteButtons = screen.getAllByRole('button', { name: '删除' });
    await user.click(deleteButtons[deleteButtons.length - 1]);
    await waitFor(() => {
      expect(screen.queryByText('carol')).not.toBeInTheDocument();
    });
  });
});
