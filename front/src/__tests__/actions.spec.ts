import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { toast } from 'vue-sonner'

import { useAcknowledgeAlert, useDecideRecommendation } from '@/lib/actions'
import { ApiError } from '@/lib/api'
import * as service from '@/services/dashboard'
import { useOperationsStore } from '@/stores/operations'

vi.mock('vue-sonner', () => ({
  toast: {
    success: vi.fn<(message: string, options?: unknown) => void>(),
    info: vi.fn<(message: string, options?: unknown) => void>(),
    error: vi.fn<(message: string, options?: unknown) => void>(),
  },
}))

describe('useDecideRecommendation : retour après une décision', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => vi.restoreAllMocks())

  it('déjà décidée par quelqu’un d’autre (409) : le dit et recharge la liste', async () => {
    const operations = useOperationsStore()
    const reload = vi.spyOn(operations, 'reloadRecommendations').mockResolvedValue()
    vi.spyOn(operations, 'decide').mockRejectedValue(new ApiError(409))

    await useDecideRecommendation()('R1', 'acceptee')

    expect(toast.info).toHaveBeenCalledWith('Recommandation déjà décidée', expect.anything())
    expect(reload).toHaveBeenCalled()
  })

  it('site que l’utilisateur ne gère pas (403) : action refusée, pas de panne', async () => {
    const operations = useOperationsStore()
    vi.spyOn(operations, 'decide').mockRejectedValue(new ApiError(403))

    await useDecideRecommendation()('R1', 'refusee')

    expect(toast.error).toHaveBeenCalledWith(
      'Action impossible',
      expect.objectContaining({
        description: 'Vous ne pouvez pas agir sur ce site.',
      }),
    )
  })

  it('décision enregistrée : confirmation', async () => {
    vi.spyOn(service, 'decideRecommendation').mockResolvedValue({ id: 'R1', statut: 'acceptee' })

    await useDecideRecommendation()('R1', 'acceptee')

    expect(toast.success).toHaveBeenCalledWith('Recommandation acceptée', expect.anything())
  })
})

describe('useAcknowledgeAlert : retour après une prise en compte', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => vi.restoreAllMocks())

  it('déjà traitée (409) : le dit et recharge les alertes', async () => {
    const operations = useOperationsStore()
    const reload = vi.spyOn(operations, 'reloadAlerts').mockResolvedValue()
    vi.spyOn(operations, 'acknowledge').mockRejectedValue(new ApiError(409))

    await useAcknowledgeAlert()('42')

    expect(toast.info).toHaveBeenCalledWith('Alerte déjà traitée', expect.anything())
    expect(reload).toHaveBeenCalled()
  })
})
