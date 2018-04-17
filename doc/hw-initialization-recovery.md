# Hardware wallet initialization and recovery

 * [Introduction](#introduction)
 * [Understanding the *recovery seed*](#understanding-the-recovery-seed)
 * [Security principles](#security-principles)
 * [Hardware wallet initialization and recovery in DMT](#hardware-wallet-initialization-and-recovery-in-dmt)
    * [Hardware wallet recovery - safe mode](hw-initr-safe-mode.md)
    * [Hardware wallet recovery - convenient mode](hw-initr-conv-mode.md)
    * [Hardware wallet recovery from hexadecimal entropy](hw-initr-entropy-mode.md)
    * [Hardware wallet initialization using newly generated seed words](hw-initr-new-seed.md)
    * [Hardware wallet wiping](hw-initr-wipe.md)
  * [Updating hardware wallet firmware](hw-initr-update-firmware.md)
 * [Running DMT on an offline Linux system](hw-initr-live-cd-linux.md)

## Introduction

Hardware wallets must be properly prepared for operation before first use. This generally takes place in one of the following two scenarios:

- Initialization: a process that consists of generating a new set of private keys and corresponding addresses on the device.

- Recovery: a process that consists of restoring an existing set of keys (and addresses) that have previously been used, e.g. in another hardware or software wallet. This method is usually used when the previous device has failed, or we are simply "migrating our funds" to another device.


Although both scenarios are supported in the official applications provided by the device manufacturers, there is a good reason to also implement this functionality in Dash Masternode Tool. This is because, despite its numerous advantages, Trezor - by far the most popular hardware wallet - has one drawback: the official client application is a web-based solution, so an internet connection is required for it to work. It is therefore impossible to initialize a Trezor on an offline computer, despite this being highly recommended considering the prevalence of malware and the potentially significant funds often managed using hardware wallets. It is also a valuable backup in case the [https://wallet.trezor.io](https://wallet.trezor.io/) website is ever unavailable for any reason, making it impossible to perform initialization or recovery, if only for a limited time.

## Understanding the *recovery seed*

All three hardware wallets supported by DMT (Trezor, KeepKey and Ledger Nano S) support the BIP32/BIP44/BIP39 standards. Without going into too much detail, it is sufficient to know that as a result:

- the device stores an entire tree of private keys and corresponding payment addresses
- all of those keys are generated based on so-called *entropy* – which is essentially a unique number with a length of 16 to 32 bytes
- for a person to be able to memorize the entropy, it is converted into a set of 12 to 24 words, later referred to as the *recovery seed*

Initialization of the device is actually the process of generating new entropy and presenting it to a user as a set of words, while recovery is the same procedure in reverse – passing a set of words forming the recovery seed to the device, and then converting them to entropy inside the device. This entropy is the basis for generating an entire set of keys, which was so brilliantly described by Andreas Antonopoulos in his groundbreaking book "Mastering Bitcoin" (see the [Wallet Technology Details](https://github.com/bitcoinbook/bitcoinbook/blob/second_edition/ch05.asciidoc#wallet-technology-details) chapter).

## Security principles

It is critical to understand that knowing the set of words comprising a recovery seed is equivalent to having access to **all** funds controlled by the keys derived from those words. So, if they get in the wrong hands, we risk losing our funds. Similarly, if we lose the recovery seed, we will also lose access to our funds. There is no known technical procedure to ever restore access.

Standard methods of device initialization and recovery are designed in such a way that they should be safe even on a computer infected with malware or viruses. But with significant funds controlled by the recovery seed, you don’t have to be paranoid to think that it would be even better to perform such activities offline. This is a particular concern for users working on Windows computers or computers which regularly download many files from the internet, exposing them to potential infection.

To such people (but not only them), it is strongly recommended to perform recovery or initialization using a Linux OS launched from a [live CD](hw-initr-live-cd-linux.md) – after the job is done, there will be no record or any data saved that could be sent to hostile server when reconnected to the internet.

## Hardware wallet initialization and recovery in DMT

All functionality described in this chapter is available in the `Hardware wallet initialization/recovery` dialog, launched from the `Tools` menu of DMT. The application will guide you through the steps using a standard wizard-style dialog, where interaction with the user is divided into separate steps.

List of available functions:

- [Hardware wallet recovery - safe mode](hw-initr-safe-mode.md)
- [Hardware wallet recovery - convenient mode](hw-initr-conv-mode.md)
- [Hardware wallet recovery from hexadecimal entropy](hw-initr-entropy-mode.md)
- [Hardware wallet initialization using newly generated seed words](hw-initr-new-seed.md)
- [Hardware wallet wiping](hw-initr-wipe.md)
- [Updating hardware wallet firmware](hw-initr-update-firmware.md)

> For Ledger Nano S wallets, only two of the above options are available (second and third) – other options are not supported by the official Ledger API, so it was not possible to create a GUI for them within DMT. This, however, is not a major problem, since these functions are already available through the device interface directly.

