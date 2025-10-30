import { redirect } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async ({ cookies }) => {
  // Clear authentication cookies
  cookies.delete('auth', { path: '/' });
  cookies.delete('acc', { path: '/' });

  // Redirect to login (303 prevents caching)
  throw redirect(303, '/login');
};
