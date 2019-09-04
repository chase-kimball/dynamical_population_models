import numpy as np

from gwpopulation.conversions import mu_chi_var_chi_max_to_alpha_beta_max
from gwpopulation.utils import beta_dist, powerlaw
from gwpopulation.cupy_utils import trapz, xp
from gwpopulation.models.mass import (
    two_component_primary_mass_ratio,
    two_component_single,
)
from gwpopulation.models.spin import iid_spin_magnitude_beta


def two_component_primary_mass_ratio_dynamical_with_spins(
    dataset,
    alpha,
    beta,
    mmin,
    mmax,
    lam,
    mpp,
    sigpp,
    alpha_chi,
    beta_chi,
    branch_1=0.12,
    branch_2=0.01,
):
    """
    Power law model for two-dimensional mass distribution, modelling primary
    mass and conditional mass ratio distribution.

    p(m1, q) = p(m1) * p(q | m1)

    We also include the effect of dynamical mergers leading to 1.5 and 2nd
    generation mergers.

    Parameters
    ----------
    dataset: dict
        Dictionary of numpy arrays for 'mass_1' and 'mass_ratio'.
    alpha: float
        Negative power law exponent for more massive black hole.
    mmin: float
        Minimum black hole mass.
    mmax: float
        Maximum black hole mass.
    beta: float
        Power law exponent of the mass ratio distribution.
    lam: float
        Fraction of black holes in the Gaussian component.
    mpp: float
        Mean of the Gaussian component.
    sigpp: float
        Standard deviation fo the Gaussian component.
    branch_1: float
        Fraction of 1.5 generation mergers.
        The default value comes from a conversation with Eric Thrane.
    branch_2: float
        Fraction of 2nd generation mergers.
        The default value comes from a conversation with Eric Thrane.
    """
    branch_0 = 1 - branch_1 - branch_2
    assert branch_0 >= 0, "Branching fractions greater than 1."
    first_generation_mass = two_component_primary_mass_ratio(
        dataset=dataset,
        alpha=alpha,
        beta=beta,
        mmin=mmin,
        mmax=mmax,
        lam=lam,
        mpp=mpp,
        sigpp=sigpp,
    )
    params = dict(
        mmin=mmin * 2, mmax=mmax * 2, lam=lam, mpp=mpp * 2, sigpp=sigpp * 2
    )
    one_point_five_generation_mass = two_component_single(
        dataset["mass_1"], alpha=alpha, **params
    ) * one_point_five_generation_mass_ratio(
        dataset, spectal_index=beta * 1.5, mmin=mmin
    )
    second_generation_mass = two_component_primary_mass_ratio(
        dataset=dataset,
        alpha=alpha,
        beta=beta * 4,
        mmin=mmin * 2,
        mmax=mmax * 2,
        lam=lam,
        mpp=mpp * 2,
        sigpp=sigpp * 2,
    )

    first_generation_spin = (
            first_generation_spin_magnitude(
                dataset["a_1"], alpha=alpha_chi, beta=beta_chi, a_max=1) *
            first_generation_spin_magnitude(
                dataset["a_2"], alpha=alpha_chi, beta=beta_chi, a_max=1)
    )

    alpha_2g, beta_2g = mu_chi_var_chi_max_to_alpha_beta_max(
        mu_chi=0.67, var_chi=0.1, amax=1
    )

    one_point_five_generation_spin = beta_dist(
        dataset["a_1"], scale=1, alpha=alpha_2g, beta=beta_2g
    ) * first_generation_spin_magnitude(
        dataset["a_2"], alpha=alpha_chi, beta=beta_chi, a_max=1)

    second_generation_spin = iid_spin_magnitude_beta(
        dataset=dataset, alpha_chi=alpha_2g, beta_chi=beta_2g, amax=1
    )

    return (
        branch_0 * first_generation_mass * first_generation_spin
        + branch_1
        * one_point_five_generation_mass
        * one_point_five_generation_spin
        + branch_2 * second_generation_mass * second_generation_spin
    )


class BigModel(object):

    def __init__(self, branching_dataset):
        self.branching_dataset = branching_dataset
        self.a_1 = xp.unique(self.branching_dataset["a_1"])
        self.a_2 = xp.unique(self.branching_dataset["a_2"])
        self.mass_ratio = xp.unique(self.branching_dataset["mass_ratio"])
        self.mass_1s = xp.linspace(3, 50, 100)
        self.mass_ratio_grid, self.mass_1_grid = xp.meshgrid(
            self.mass_ratio, self.mass_1s)
        self.first_generation_data = dict(
            mass_1=self.mass_1_grid, mass_ratio=self.mass_ratio_grid)

    def __call__(self, dataset, alpha, beta, mmin, mmax, lam, mpp, sigpp,
                 alpha_chi, beta_chi):
        branching_fraction = self.compute_branching_fraction(
            alpha=alpha, beta=beta, mmin=mmin, mmax=mmax, lam=lam, mpp=mpp,
            sigpp=sigpp, alpha_chi=alpha_chi, beta_chi=beta_chi
        )
        return two_component_primary_mass_ratio_dynamical_with_spins(
            dataset=dataset,
            alpha=alpha,
            beta=beta,
            mmin=mmin,
            mmax=mmax,
            lam=lam,
            mpp=mpp,
            sigpp=sigpp,
            alpha_chi=alpha_chi,
            beta_chi=beta_chi,
            branch_1=2 / 3 * branching_fraction,
            branch_2=branching_fraction**2 / 4
        )

    def compute_branching_fraction(self, alpha, beta, mmin, mmax, lam, mpp,
                                   sigpp, alpha_chi, beta_chi, a_max=1):
        probability = (
            self.first_generation_mass_ratio(
                alpha=alpha, beta=beta, mmin=mmin, mmax=mmax, lam=lam, mpp=mpp,
                sigpp=sigpp) *
            first_generation_spin_magnitude(
                self.branching_dataset["a_1"],
                alpha=alpha_chi, beta=beta_chi, a_max=a_max) *
            first_generation_spin_magnitude(
                self.branching_dataset["a_2"],
                alpha=alpha_chi, beta=beta_chi, a_max=a_max)
        )
        branching_fraction = trapz(trapz(trapz(
            probability * self.branching_dataset["interpolated_retention_fraction"],
            self.mass_ratio), self.a_2), self.a_1)
        return branching_fraction

    def first_generation_mass_ratio(
            self, alpha, beta, mmin, mmax, lam, mpp, sigpp):
        first_generation_mass = two_component_primary_mass_ratio(
            dataset=self.first_generation_data,
            alpha=alpha,
            beta=beta,
            mmin=mmin,
            mmax=mmax,
            lam=lam,
            mpp=mpp,
            sigpp=sigpp,
        )
        first_generation_mass_ratio = trapz(first_generation_mass, self.mass_1s)
        return xp.atleast_3d(first_generation_mass_ratio)


def first_generation_spin_magnitude(spin, alpha, beta, a_max):
    fraction_equal_zero = xp.mean(spin == 0)
    return (
        fraction_equal_zero +
        (1 - fraction_equal_zero) *
        beta_dist(xx=spin, alpha=alpha, beta=beta, scale=a_max)
    )


def two_component_primary_mass_ratio_dynamical(
    dataset,
    alpha,
    beta,
    mmin,
    mmax,
    lam,
    mpp,
    sigpp,
    branch_1=0.12,
    branch_2=0.01,
):
    """
    Power law model for two-dimensional mass distribution, modelling primary
    mass and conditional mass ratio distribution.

    p(m1, q) = p(m1) * p(q | m1)

    We also include the effect of dynamical mergers leading to 1.5 and 2nd
    generation mergers.

    Parameters
    ----------
    dataset: dict
        Dictionary of numpy arrays for 'mass_1' and 'mass_ratio'.
    alpha: float
        Negative power law exponent for more massive black hole.
    mmin: float
        Minimum black hole mass.
    mmax: float
        Maximum black hole mass.
    beta: float
        Power law exponent of the mass ratio distribution.
    lam: float
        Fraction of black holes in the Gaussian component.
    mpp: float
        Mean of the Gaussian component.
    sigpp: float
        Standard deviation fo the Gaussian component.
    branch_1: float
        Fraction of 1.5 generation mergers.
        The default value comes from a conversation with Eric Thrane.
    branch_2: float
        Fraction of 2nd generation mergers.
        The default value comes from a conversation with Eric Thrane.
    """
    branch_0 = 1 - branch_1 - branch_2
    if branch_0 < 0:
        return np.zeros_like(dataset["mass_1"])
    # assert branch_0 >= 0, "Branching fractions greater than 1."
    first_generation = two_component_primary_mass_ratio(
        dataset=dataset,
        alpha=alpha,
        beta=beta,
        mmin=mmin,
        mmax=mmax,
        lam=lam,
        mpp=mpp,
        sigpp=sigpp,
    )
    params = dict(
        mmin=mmin * 2, mmax=mmax * 2, lam=lam, mpp=mpp * 2, sigpp=sigpp * 2
    )
    one_point_five_generation = two_component_single(
        dataset["mass_1"], alpha=alpha, **params
    ) * one_point_five_generation_mass_ratio(
        dataset, spectal_index=beta * 1.5, mmin=mmin
    )
    second_generation = two_component_primary_mass_ratio(
        dataset=dataset,
        alpha=alpha,
        beta=beta * 4,
        mmin=mmin * 2,
        mmax=mmax * 2,
        lam=lam,
        mpp=mpp * 2,
        sigpp=sigpp * 2,
    )
    return (
        branch_0 * first_generation
        + branch_1 * one_point_five_generation
        + branch_2 * second_generation
    )


def one_point_five_generation_mass_ratio(dataset, spectal_index, mmin):
    split = (1 + mmin / dataset["mass_1"]) / 2
    prob = (
        powerlaw(
            dataset["mass_ratio"],
            spectal_index,
            high=split,
            low=mmin / dataset["mass_1"],
        )
        * (dataset["mass_ratio"] <= split)
        + powerlaw(
            1 - dataset["mass_ratio"],
            spectal_index,
            high=split,
            low=mmin / dataset["mass_1"],
        )
        * (dataset["mass_ratio"] >= split)
    ) / 2
    return prob
