import { createApp } from 'vue'
import { VueQueryPlugin } from '@tanstack/vue-query'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import Overview from './pages/Overview.vue'
import Examples from './pages/Examples.vue'
import Walkthrough from './pages/Walkthrough.vue'
import ProductStory from './pages/ProductStory.vue'
import Catalog from './pages/Catalog.vue'
import Import from './pages/Import.vue'
import Sources from './pages/Sources.vue'
import Schemas from './pages/Schemas.vue'
import Runs from './pages/Runs.vue'
import Review from './pages/Review.vue'
import Exports from './pages/Exports.vue'
import Settings from './pages/Settings.vue'
import Product from './pages/Product.vue'
import './style.css'
import './experience.css'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/product-story', component: ProductStory, meta: { title: 'CatalogForge', public: true } },
    { path: '/walkthrough', component: Walkthrough, meta: { title: 'Guided walkthrough' } },
    { path: '/', component: Overview, meta: { title: 'Overview' } },
    { path: '/examples', component: Examples, meta: { title: 'Guided examples' } },
    { path: '/catalog', component: Catalog, meta: { title: 'Product catalog' } },
    { path: '/import', component: Import, meta: { title: 'Import catalog' } },
    { path: '/products/:id', component: Product, meta: { title: 'Product detail' } },
    { path: '/sources/:id?', component: Sources, meta: { title: 'Source library' } },
    { path: '/schemas', component: Schemas, meta: { title: 'Category schemas' } },
    { path: '/runs', component: Runs, meta: { title: 'Enrichment runs' } },
    { path: '/review/:id?', component: Review, meta: { title: 'Review workspace' } },
    { path: '/exports', component: Exports, meta: { title: 'Exports' } },
    { path: '/settings', component: Settings, meta: { title: 'Settings' } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
createApp(App).use(router).use(VueQueryPlugin, { queryClientConfig: { defaultOptions: { queries: { staleTime: 1000, refetchOnWindowFocus: true } } } }).mount('#app')
