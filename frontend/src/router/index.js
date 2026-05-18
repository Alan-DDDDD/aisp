import { createRouter, createWebHistory } from 'vue-router'

const ChatPage = () => import('../pages/ChatPage.vue')
const AdminWorkspaces = () => import('../pages/admin/AdminWorkspaces.vue')
const AdminWorkspaceDetail = () => import('../pages/admin/AdminWorkspaceDetail.vue')
const AdminKbDetail = () => import('../pages/admin/AdminKbDetail.vue')
const AdminTraces = () => import('../pages/admin/AdminTraces.vue')
const AdminSynthesis = () => import('../pages/admin/AdminSynthesis.vue')

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'chat', component: ChatPage },
    { path: '/admin', name: 'admin', component: AdminWorkspaces },
    {
      path: '/admin/workspaces/:id',
      name: 'admin-workspace',
      component: AdminWorkspaceDetail,
      props: true,
    },
    { path: '/admin/kbs/:id', name: 'admin-kb', component: AdminKbDetail, props: true },
    { path: '/admin/traces', name: 'admin-traces', component: AdminTraces },
    { path: '/admin/synthesis', name: 'admin-synthesis', component: AdminSynthesis },
  ],
})
