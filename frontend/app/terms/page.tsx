"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronLeft } from "lucide-react";

export default function TermsPage() {
  const router = useRouter();

  return (
    <div className="min-h-screen px-6 py-12" style={{ background: "var(--bg)" }}>
      <div className="max-w-3xl mx-auto">
        <button
          onClick={() => router.back()}
          className="inline-flex items-center gap-1.5 text-sm mb-8 hover:underline"
          style={{ color: "var(--text-secondary)" }}
        >
          <ChevronLeft className="w-4 h-4" />
          Back
        </button>

        <article
          className="rounded-xl p-8 leading-relaxed"
          style={{
            background: "var(--bg-card)",
            border: "1px solid var(--border)",
            color: "var(--text-secondary)",
          }}
        >
          <h1
            className="text-3xl font-bold mb-2"
            style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}
          >
            Terms of Service
          </h1>
          <p className="text-xs mb-8" style={{ color: "var(--text-muted)" }}>
            Last updated May 13, 2026
          </p>

          <H2>Agreement to our Legal Terms</H2>
          <P>
            We are <Em>Up 2 Code Inc.</Em>, doing business as Architechtura (&quot;Company,&quot;
            &quot;we,&quot; &quot;us,&quot; &quot;our&quot;), a company registered in Washington,
            United States at 4751 21st Ave NE, 105, Seattle, WA 98105.
          </P>
          <P>
            We operate the website{" "}
            <ExtLink href="http://www.up2code.ai">http://www.up2code.ai</ExtLink> (the
            &quot;Site&quot;), as well as any other related products and services that refer or link
            to these legal terms (the &quot;Legal Terms&quot;) (collectively, the &quot;Services&quot;).
          </P>
          <P>
            You can contact us by phone at 805-630-1611, email at{" "}
            <ExtLink href="mailto:esmith.marc@gmail.com">esmith.marc@gmail.com</ExtLink>, or by mail
            to 4751 21st Ave NE, 105, Seattle, WA 98105, United States.
          </P>
          <P>
            These Legal Terms constitute a legally binding agreement made between you, whether
            personally or on behalf of an entity (&quot;you&quot;), and Up 2 Code Inc., concerning
            your access to and use of the Services. You agree that by accessing the Services, you
            have read, understood, and agreed to be bound by all of these Legal Terms. IF YOU DO NOT
            AGREE WITH ALL OF THESE LEGAL TERMS, THEN YOU ARE EXPRESSLY PROHIBITED FROM USING THE
            SERVICES AND YOU MUST DISCONTINUE USE IMMEDIATELY.
          </P>
          <P>
            Supplemental terms and conditions or documents that may be posted on the Services from
            time to time are hereby expressly incorporated herein by reference. We reserve the right,
            in our sole discretion, to make changes or modifications to these Legal Terms at any time
            and for any reason. We will alert you about any changes by updating the &quot;Last
            updated&quot; date of these Legal Terms, and you waive any right to receive specific
            notice of each such change.
          </P>
          <P>
            The Services are intended for users who are at least 13 years of age. All users who are
            minors in the jurisdiction in which they reside (generally under the age of 18) must have
            the permission of, and be directly supervised by, their parent or guardian to use the
            Services.
          </P>
          <P>We recommend that you print a copy of these Legal Terms for your records.</P>

          <H2>Table of Contents</H2>
          <ol className="list-decimal pl-6 mb-8 space-y-1 text-sm">
            <li><Toc href="#services">Our Services</Toc></li>
            <li><Toc href="#ip">Intellectual Property Rights</Toc></li>
            <li><Toc href="#userreps">User Representations</Toc></li>
            <li><Toc href="#userreg">User Registration</Toc></li>
            <li><Toc href="#purchases">Purchases and Payment</Toc></li>
            <li><Toc href="#subscriptions">Subscriptions</Toc></li>
            <li><Toc href="#prohibited">Prohibited Activities</Toc></li>
            <li><Toc href="#ugc">User Generated Contributions</Toc></li>
            <li><Toc href="#license">Contribution License</Toc></li>
            <li><Toc href="#sitemanage">Services Management</Toc></li>
            <li><Toc href="#ppyes">Privacy Policy</Toc></li>
            <li><Toc href="#terms">Term and Termination</Toc></li>
            <li><Toc href="#modifications">Modifications and Interruptions</Toc></li>
            <li><Toc href="#law">Governing Law</Toc></li>
            <li><Toc href="#disputes">Dispute Resolution</Toc></li>
            <li><Toc href="#corrections">Corrections</Toc></li>
            <li><Toc href="#disclaimer">Disclaimer</Toc></li>
            <li><Toc href="#liability">Limitations of Liability</Toc></li>
            <li><Toc href="#indemnification">Indemnification</Toc></li>
            <li><Toc href="#userdata">User Data</Toc></li>
            <li><Toc href="#electronic">Electronic Communications, Transactions, and Signatures</Toc></li>
            <li><Toc href="#california">California Users and Residents</Toc></li>
            <li><Toc href="#misc">Miscellaneous</Toc></li>
            <li><Toc href="#contact">Contact Us</Toc></li>
          </ol>

          <Section id="services" title="1. Our Services">
            <P>
              The information provided when using the Services is not intended for distribution to or
              use by any person or entity in any jurisdiction or country where such distribution or
              use would be contrary to law or regulation. Accordingly, those persons who choose to
              access the Services from other locations do so on their own initiative and are solely
              responsible for compliance with local laws, if and to the extent local laws are
              applicable.
            </P>
            <P>
              The Services are not tailored to comply with industry-specific regulations (HIPAA,
              FISMA, etc.), so if your interactions would be subjected to such laws, you may not use
              the Services. You may not use the Services in a way that would violate the
              Gramm-Leach-Bliley Act (GLBA).
            </P>
          </Section>

          <Section id="ip" title="2. Intellectual Property Rights">
            <H3>Our intellectual property</H3>
            <P>
              We are the owner or the licensee of all intellectual property rights in our Services,
              including all source code, databases, functionality, software, website designs, audio,
              video, text, photographs, and graphics in the Services (collectively, the
              &quot;Content&quot;), as well as the trademarks, service marks, and logos contained
              therein (the &quot;Marks&quot;).
            </P>
            <P>
              Our Content and Marks are protected by copyright and trademark laws (and various other
              intellectual property rights and unfair competition laws) and treaties in the United
              States and around the world.
            </P>
            <P>
              The Content and Marks are provided in or through the Services &quot;AS IS&quot; for
              your personal, non-commercial use or internal business purpose only.
            </P>

            <H3>Your use of our Services</H3>
            <P>
              Subject to your compliance with these Legal Terms, including the &quot;PROHIBITED
              ACTIVITIES&quot; section below, we grant you a non-exclusive, non-transferable,
              revocable license to:
            </P>
            <ul className="list-disc pl-6 mb-4 space-y-1">
              <li>access the Services; and</li>
              <li>download or print a copy of any portion of the Content to which you have properly gained access,</li>
            </ul>
            <P>solely for your personal, non-commercial use or internal business purpose.</P>
            <P>
              Except as set out in this section or elsewhere in our Legal Terms, no part of the
              Services and no Content or Marks may be copied, reproduced, aggregated, republished,
              uploaded, posted, publicly displayed, encoded, translated, transmitted, distributed,
              sold, licensed, or otherwise exploited for any commercial purpose whatsoever, without
              our express prior written permission.
            </P>
            <P>
              If you wish to make any use of the Services, Content, or Marks other than as set out in
              this section, please email{" "}
              <ExtLink href="mailto:esmith.marc@gmail.com">esmith.marc@gmail.com</ExtLink>. We reserve
              all rights not expressly granted to you in and to the Services, Content, and Marks.
            </P>
            <P>
              Any breach of these Intellectual Property Rights will constitute a material breach of
              our Legal Terms and your right to use our Services will terminate immediately.
            </P>

            <H3>Your submissions</H3>
            <P>
              <Em>Submissions:</Em> By directly sending us any question, comment, suggestion, idea,
              feedback, or other information about the Services (&quot;Submissions&quot;), you agree
              to assign to us all intellectual property rights in such Submission. You agree that we
              shall own this Submission and be entitled to its unrestricted use and dissemination for
              any lawful purpose, commercial or otherwise, without acknowledgment or compensation to
              you.
            </P>
            <P>
              <Em>You are responsible for what you post or upload:</Em> By sending us Submissions
              through any part of the Services you confirm that you have read and agree with our
              &quot;PROHIBITED ACTIVITIES&quot; and will not post, send, publish, upload, or transmit
              through the Services any Submission that is illegal, harassing, hateful, harmful,
              defamatory, obscene, bullying, abusive, discriminatory, threatening, sexually explicit,
              false, inaccurate, deceitful, or misleading; to the extent permissible by applicable
              law, you waive any and all moral rights to any such Submission; you warrant that any
              such Submission is original to you or that you have the necessary rights and licenses;
              and that your Submissions do not constitute confidential information.
            </P>
            <P>
              You are solely responsible for your Submissions and you expressly agree to reimburse us
              for any and all losses that we may suffer because of your breach of (a) this section,
              (b) any third party&apos;s intellectual property rights, or (c) applicable law.
            </P>
          </Section>

          <Section id="userreps" title="3. User Representations">
            <P>By using the Services, you represent and warrant that:</P>
            <ol className="list-decimal pl-6 mb-4 space-y-1">
              <li>all registration information you submit will be true, accurate, current, and complete;</li>
              <li>you will maintain the accuracy of such information and promptly update such registration information as necessary;</li>
              <li>you have the legal capacity and you agree to comply with these Legal Terms;</li>
              <li>you are not under the age of 13;</li>
              <li>you are not a minor in the jurisdiction in which you reside, or if a minor, you have received parental permission to use the Services;</li>
              <li>you will not access the Services through automated or non-human means, whether through a bot, script or otherwise;</li>
              <li>you will not use the Services for any illegal or unauthorized purpose; and</li>
              <li>your use of the Services will not violate any applicable law or regulation.</li>
            </ol>
            <P>
              If you provide any information that is untrue, inaccurate, not current, or incomplete,
              we have the right to suspend or terminate your account and refuse any and all current
              or future use of the Services (or any portion thereof).
            </P>
          </Section>

          <Section id="userreg" title="4. User Registration">
            <P>
              You may be required to register to use the Services. You agree to keep your password
              confidential and will be responsible for all use of your account and password. We
              reserve the right to remove, reclaim, or change a username you select if we determine,
              in our sole discretion, that such username is inappropriate, obscene, or otherwise
              objectionable.
            </P>
          </Section>

          <Section id="purchases" title="5. Purchases and Payment">
            <P>We accept the following forms of payment:</P>
            <ul className="list-disc pl-6 mb-4 space-y-1">
              <li>Visa</li>
              <li>Mastercard</li>
              <li>American Express</li>
              <li>Discover</li>
            </ul>
            <P>
              You agree to provide current, complete, and accurate purchase and account information
              for all purchases made via the Services. You further agree to promptly update account
              and payment information, including email address, payment method, and payment card
              expiration date, so that we can complete your transactions and contact you as needed.
              Sales tax will be added to the price of purchases as deemed required by us. We may
              change prices at any time. All payments shall be in US dollars.
            </P>
            <P>
              You agree to pay all charges at the prices then in effect for your purchases and any
              applicable shipping fees, and you authorize us to charge your chosen payment provider
              for any such amounts upon placing your order. We reserve the right to correct any
              errors or mistakes in pricing, even if we have already requested or received payment.
            </P>
            <P>
              We reserve the right to refuse any order placed through the Services. We may, in our
              sole discretion, limit or cancel quantities purchased per person, per household, or per
              order.
            </P>
          </Section>

          <Section id="subscriptions" title="6. Subscriptions">
            <H3>Billing and Renewal</H3>
            <P>
              Your subscription will continue and automatically renew unless canceled. You consent to
              our charging your payment method on a recurring basis without requiring your prior
              approval for each recurring charge, until such time as you cancel the applicable order.
              The length of your billing cycle is monthly.
            </P>
            <H3>Cancellation</H3>
            <P>
              All purchases are non-refundable. You can cancel your subscription at any time by
              logging into your account. Your cancellation will take effect at the end of the current
              paid term. If you have any questions or are unsatisfied with our Services, please email
              us at{" "}
              <ExtLink href="mailto:esmith.marc@gmail.com">esmith.marc@gmail.com</ExtLink>.
            </P>
            <H3>Fee Changes</H3>
            <P>
              We may, from time to time, make changes to the subscription fee and will communicate
              any price changes to you in accordance with applicable law.
            </P>
          </Section>

          <Section id="prohibited" title="7. Prohibited Activities">
            <P>
              You may not access or use the Services for any purpose other than that for which we
              make the Services available. The Services may not be used in connection with any
              commercial endeavors except those that are specifically endorsed or approved by us.
            </P>
            <P>As a user of the Services, you agree not to:</P>
            <ul className="list-disc pl-6 mb-4 space-y-1.5 text-sm">
              <li>Systematically retrieve data or other content from the Services to create or compile, directly or indirectly, a collection, compilation, database, or directory without written permission from us.</li>
              <li>Trick, defraud, or mislead us and other users, especially in any attempt to learn sensitive account information such as user passwords.</li>
              <li>Circumvent, disable, or otherwise interfere with security-related features of the Services.</li>
              <li>Disparage, tarnish, or otherwise harm, in our opinion, us and/or the Services.</li>
              <li>Use any information obtained from the Services in order to harass, abuse, or harm another person.</li>
              <li>Make improper use of our support services or submit false reports of abuse or misconduct.</li>
              <li>Use the Services in a manner inconsistent with any applicable laws or regulations.</li>
              <li>Engage in unauthorized framing of or linking to the Services.</li>
              <li>Upload or transmit viruses, Trojan horses, or other malicious material that interferes with the Services.</li>
              <li>Engage in any automated use of the system, such as using scripts or data-mining tools.</li>
              <li>Delete the copyright or other proprietary rights notice from any Content.</li>
              <li>Attempt to impersonate another user or person or use the username of another user.</li>
              <li>Upload or transmit passive information collection or transmission mechanisms (spyware, web bugs, pcms, etc.).</li>
              <li>Interfere with, disrupt, or create an undue burden on the Services or the networks or services connected to the Services.</li>
              <li>Harass, annoy, intimidate, or threaten any of our employees or agents.</li>
              <li>Attempt to bypass any measures designed to prevent or restrict access to the Services.</li>
              <li>Copy or adapt the Services&apos; software.</li>
              <li>Except as permitted by applicable law, decipher, decompile, disassemble, or reverse engineer any software comprising the Services.</li>
              <li>Use, launch, develop, or distribute any automated system, including any spider, robot, scraper, or offline reader.</li>
              <li>Use a buying agent or purchasing agent to make purchases on the Services.</li>
              <li>Make any unauthorized use of the Services, including collecting usernames or email addresses by electronic or other means, or creating user accounts by automated means or under false pretenses.</li>
              <li>Use the Services as part of any effort to compete with us, or for any revenue-generating endeavor or commercial enterprise.</li>
              <li>Use the Services to advertise or offer to sell goods and services.</li>
              <li>Sell or otherwise transfer your profile.</li>
            </ul>
          </Section>

          <Section id="ugc" title="8. User Generated Contributions">
            <P>
              The Services may provide you the opportunity to create, submit, post, display,
              transmit, perform, publish, distribute, or broadcast content to us or on the Services,
              including text, writings, video, audio, photographs, graphics, comments, suggestions,
              or personal information (collectively, &quot;Contributions&quot;). Contributions may be
              viewable by other users. By making any Contributions, you represent and warrant that:
            </P>
            <ul className="list-disc pl-6 mb-4 space-y-1.5 text-sm">
              <li>Your Contributions do not infringe the proprietary rights of any third party.</li>
              <li>You have the necessary licenses, rights, consents, releases, and permissions to use and authorize us to use your Contributions.</li>
              <li>You have written consent of each identifiable person in your Contributions to use their name or likeness.</li>
              <li>Your Contributions are not false, inaccurate, or misleading.</li>
              <li>Your Contributions are not unsolicited or unauthorized advertising, promotional materials, pyramid schemes, chain letters, spam, or solicitations.</li>
              <li>Your Contributions are not obscene, lewd, lascivious, filthy, violent, harassing, libelous, slanderous, or otherwise objectionable.</li>
              <li>Your Contributions do not ridicule, mock, disparage, intimidate, or abuse anyone.</li>
              <li>Your Contributions are not used to harass or threaten any other person or promote violence.</li>
              <li>Your Contributions do not violate any applicable law, regulation, or rule.</li>
              <li>Your Contributions do not violate the privacy or publicity rights of any third party.</li>
              <li>Your Contributions do not violate any law concerning child pornography or otherwise intended to protect the health or well-being of minors.</li>
              <li>Your Contributions do not include any offensive comments connected to race, national origin, gender, sexual preference, or physical handicap.</li>
              <li>Your Contributions do not otherwise violate any provision of these Legal Terms or any applicable law.</li>
            </ul>
          </Section>

          <Section id="license" title="9. Contribution License">
            <P>
              You and Services agree that we may access, store, process, and use any information and
              personal data that you provide following the terms of the Privacy Policy and your
              choices (including settings).
            </P>
            <P>
              By submitting suggestions or other feedback regarding the Services, you agree that we
              can use and share such feedback for any purpose without compensation to you.
            </P>
            <P>
              We do not assert any ownership over your Contributions. You retain full ownership of
              all of your Contributions and any intellectual property rights or other proprietary
              rights associated with your Contributions.
            </P>
          </Section>

          <Section id="sitemanage" title="10. Services Management">
            <P>
              We reserve the right, but not the obligation, to: (1) monitor the Services for
              violations of these Legal Terms; (2) take appropriate legal action against anyone who,
              in our sole discretion, violates the law or these Legal Terms; (3) refuse, restrict
              access to, limit the availability of, or disable any of your Contributions; (4) remove
              from the Services or otherwise disable all files and content that are excessive in size
              or are in any way burdensome to our systems; and (5) otherwise manage the Services in a
              manner designed to protect our rights and property and to facilitate the proper
              functioning of the Services.
            </P>
          </Section>

          <Section id="ppyes" title="11. Privacy Policy">
            <P>
              We care about data privacy and security. Please review our{" "}
              <Link href="/privacy" className="hover:underline" style={{ color: "var(--accent-bright)" }}>
                Privacy Policy
              </Link>
              . By using the Services, you agree to be bound by our Privacy Policy, which is
              incorporated into these Legal Terms. The Services are hosted in the United States. If
              you access the Services from any other region of the world with laws or other
              requirements governing personal data, you are transferring your data to the United
              States and you expressly consent to have your data transferred to and processed in the
              United States.
            </P>
            <P>
              We do not knowingly accept, request, or solicit information from children or knowingly
              market to children. If we receive actual knowledge that anyone under 13 has provided
              personal information to us, we will delete that information from the Services as
              quickly as is reasonably practical.
            </P>
          </Section>

          <Section id="terms" title="12. Term and Termination">
            <P>
              These Legal Terms shall remain in full force and effect while you use the Services.
              WITHOUT LIMITING ANY OTHER PROVISION OF THESE LEGAL TERMS, WE RESERVE THE RIGHT TO, IN
              OUR SOLE DISCRETION AND WITHOUT NOTICE OR LIABILITY, DENY ACCESS TO AND USE OF THE
              SERVICES (INCLUDING BLOCKING CERTAIN IP ADDRESSES), TO ANY PERSON FOR ANY REASON OR FOR
              NO REASON. WE MAY TERMINATE YOUR USE OR PARTICIPATION IN THE SERVICES OR DELETE YOUR
              ACCOUNT AND ANY CONTENT OR INFORMATION THAT YOU POSTED AT ANY TIME, WITHOUT WARNING, IN
              OUR SOLE DISCRETION.
            </P>
            <P>
              If we terminate or suspend your account, you are prohibited from registering and
              creating a new account under your name, a fake or borrowed name, or the name of any
              third party.
            </P>
          </Section>

          <Section id="modifications" title="13. Modifications and Interruptions">
            <P>
              We reserve the right to change, modify, or remove the contents of the Services at any
              time or for any reason at our sole discretion without notice. We will not be liable to
              you or any third party for any modification, price change, suspension, or discontinuance
              of the Services.
            </P>
            <P>
              We cannot guarantee the Services will be available at all times. We may experience
              hardware, software, or other problems or need to perform maintenance, resulting in
              interruptions, delays, or errors. You agree that we have no liability whatsoever for
              any loss, damage, or inconvenience caused by your inability to access or use the
              Services during any downtime or discontinuance.
            </P>
          </Section>

          <Section id="law" title="14. Governing Law">
            <P>
              These Legal Terms and your use of the Services are governed by and construed in
              accordance with the laws of the State of California applicable to agreements made and
              to be entirely performed within the State of California, without regard to its conflict
              of law principles.
            </P>
          </Section>

          <Section id="disputes" title="15. Dispute Resolution">
            <H3>Informal Negotiations</H3>
            <P>
              To expedite resolution and control the cost of any dispute, controversy, or claim
              related to these Legal Terms (each a &quot;Dispute&quot; and collectively, the
              &quot;Disputes&quot;) brought by either you or us (individually, a &quot;Party&quot;
              and collectively, the &quot;Parties&quot;), the Parties agree to first attempt to
              negotiate any Dispute (except those expressly provided below) informally for at least
              one hundred twenty nine (129) days before initiating arbitration.
            </P>
            <H3>Binding Arbitration</H3>
            <P>
              If the Parties are unable to resolve a Dispute through informal negotiations, the
              Dispute (except those expressly excluded below) will be finally and exclusively
              resolved by binding arbitration. YOU UNDERSTAND THAT WITHOUT THIS PROVISION, YOU WOULD
              HAVE THE RIGHT TO SUE IN COURT AND HAVE A JURY TRIAL. The arbitration shall be
              commenced and conducted under the Commercial Arbitration Rules of the American
              Arbitration Association (&quot;AAA&quot;). The arbitration may be conducted in person,
              through the submission of documents, by phone, or online. Except where otherwise
              required, the arbitration will take place in Ventura County, California.
            </P>
            <P>
              If for any reason a Dispute proceeds in court rather than arbitration, the Dispute
              shall be commenced or prosecuted in the state and federal courts located in Ventura
              County, California.
            </P>
            <H3>Restrictions</H3>
            <P>
              The Parties agree that any arbitration shall be limited to the Dispute between the
              Parties individually. No arbitration shall be joined with any other proceeding; there
              is no right or authority for any Dispute to be arbitrated on a class-action basis; and
              there is no right or authority for any Dispute to be brought in a purported
              representative capacity on behalf of the general public.
            </P>
            <H3>Exceptions to Informal Negotiations and Arbitration</H3>
            <P>
              The following Disputes are not subject to the above provisions: (a) any Disputes
              seeking to enforce or protect, or concerning the validity of, any of the intellectual
              property rights of a Party; (b) any Dispute related to allegations of theft, piracy,
              invasion of privacy, or unauthorized use; and (c) any claim for injunctive relief.
            </P>
          </Section>

          <Section id="corrections" title="16. Corrections">
            <P>
              There may be information on the Services that contains typographical errors,
              inaccuracies, or omissions, including descriptions, pricing, availability, and various
              other information. We reserve the right to correct any errors and to update the
              information on the Services at any time, without prior notice.
            </P>
          </Section>

          <Section id="disclaimer" title="17. Disclaimer">
            <P>
              THE SERVICES ARE PROVIDED ON AN AS-IS AND AS-AVAILABLE BASIS. YOU AGREE THAT YOUR USE
              OF THE SERVICES WILL BE AT YOUR SOLE RISK. TO THE FULLEST EXTENT PERMITTED BY LAW, WE
              DISCLAIM ALL WARRANTIES, EXPRESS OR IMPLIED, IN CONNECTION WITH THE SERVICES AND YOUR
              USE THEREOF, INCLUDING THE IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
              PARTICULAR PURPOSE, AND NON-INFRINGEMENT. WE MAKE NO WARRANTIES OR REPRESENTATIONS
              ABOUT THE ACCURACY OR COMPLETENESS OF THE SERVICES&apos; CONTENT AND WE ASSUME NO
              LIABILITY OR RESPONSIBILITY FOR ANY (1) ERRORS, MISTAKES, OR INACCURACIES OF CONTENT;
              (2) PERSONAL INJURY OR PROPERTY DAMAGE, OF ANY NATURE WHATSOEVER, RESULTING FROM YOUR
              ACCESS TO AND USE OF THE SERVICES; (3) ANY UNAUTHORIZED ACCESS TO OR USE OF OUR SECURE
              SERVERS AND/OR ANY AND ALL PERSONAL INFORMATION; (4) ANY INTERRUPTION OR CESSATION OF
              TRANSMISSION TO OR FROM THE SERVICES; (5) ANY BUGS, VIRUSES, TROJAN HORSES, OR THE LIKE
              WHICH MAY BE TRANSMITTED TO OR THROUGH THE SERVICES BY ANY THIRD PARTY; AND/OR (6) ANY
              ERRORS OR OMISSIONS IN ANY CONTENT OR FOR ANY LOSS OR DAMAGE INCURRED AS A RESULT OF
              THE USE OF ANY CONTENT POSTED, TRANSMITTED, OR OTHERWISE MADE AVAILABLE VIA THE
              SERVICES.
            </P>
          </Section>

          <Section id="liability" title="18. Limitations of Liability">
            <P>
              IN NO EVENT WILL WE OR OUR DIRECTORS, EMPLOYEES, OR AGENTS BE LIABLE TO YOU OR ANY
              THIRD PARTY FOR ANY DIRECT, INDIRECT, CONSEQUENTIAL, EXEMPLARY, INCIDENTAL, SPECIAL, OR
              PUNITIVE DAMAGES, INCLUDING LOST PROFIT, LOST REVENUE, LOSS OF DATA, OR OTHER DAMAGES
              ARISING FROM YOUR USE OF THE SERVICES, EVEN IF WE HAVE BEEN ADVISED OF THE POSSIBILITY
              OF SUCH DAMAGES. NOTWITHSTANDING ANYTHING TO THE CONTRARY CONTAINED HEREIN, OUR
              LIABILITY TO YOU FOR ANY CAUSE WHATSOEVER AND REGARDLESS OF THE FORM OF THE ACTION,
              WILL AT ALL TIMES BE LIMITED TO THE LESSER OF THE AMOUNT PAID, IF ANY, BY YOU TO US
              DURING THE ONE (1) MONTH PERIOD PRIOR TO ANY CAUSE OF ACTION ARISING OR $100.00 USD.
            </P>
            <P>
              CERTAIN US STATE LAWS AND INTERNATIONAL LAWS DO NOT ALLOW LIMITATIONS ON IMPLIED
              WARRANTIES OR THE EXCLUSION OR LIMITATION OF CERTAIN DAMAGES. IF THESE LAWS APPLY TO
              YOU, SOME OR ALL OF THE ABOVE DISCLAIMERS OR LIMITATIONS MAY NOT APPLY TO YOU, AND YOU
              MAY HAVE ADDITIONAL RIGHTS.
            </P>
          </Section>

          <Section id="indemnification" title="19. Indemnification">
            <P>
              You agree to defend, indemnify, and hold us harmless, including our subsidiaries,
              affiliates, and all of our respective officers, agents, partners, and employees, from
              and against any loss, damage, liability, claim, or demand, including reasonable
              attorneys&apos; fees and expenses, made by any third party due to or arising out of:
              (1) use of the Services; (2) breach of these Legal Terms; (3) any breach of your
              representations and warranties; (4) your violation of the rights of a third party,
              including intellectual property rights; or (5) any overt harmful act toward any other
              user of the Services.
            </P>
          </Section>

          <Section id="userdata" title="20. User Data">
            <P>
              We will maintain certain data that you transmit to the Services for the purpose of
              managing the performance of the Services, as well as data relating to your use of the
              Services. Although we perform regular routine backups of data, you are solely
              responsible for all data that you transmit or that relates to any activity you have
              undertaken using the Services. You agree that we shall have no liability to you for any
              loss or corruption of any such data.
            </P>
          </Section>

          <Section id="electronic" title="21. Electronic Communications, Transactions, and Signatures">
            <P>
              Visiting the Services, sending us emails, and completing online forms constitute
              electronic communications. You consent to receive electronic communications, and you
              agree that all agreements, notices, disclosures, and other communications we provide to
              you electronically, via email and on the Services, satisfy any legal requirement that
              such communication be in writing. YOU HEREBY AGREE TO THE USE OF ELECTRONIC SIGNATURES,
              CONTRACTS, ORDERS, AND OTHER RECORDS.
            </P>
          </Section>

          <Section id="california" title="22. California Users and Residents">
            <P>
              If any complaint with us is not satisfactorily resolved, you can contact the Complaint
              Assistance Unit of the Division of Consumer Services of the California Department of
              Consumer Affairs in writing at 1625 North Market Blvd., Suite N 112, Sacramento,
              California 95834 or by telephone at (800) 952-5210 or (916) 445-1254.
            </P>
          </Section>

          <Section id="misc" title="23. Miscellaneous">
            <P>
              These Legal Terms and any policies or operating rules posted by us on the Services
              constitute the entire agreement and understanding between you and us. Our failure to
              exercise or enforce any right or provision of these Legal Terms shall not operate as a
              waiver of such right or provision. These Legal Terms operate to the fullest extent
              permissible by law. We may assign any or all of our rights and obligations to others at
              any time. If any provision is determined to be unlawful, void, or unenforceable, that
              provision is deemed severable and does not affect the validity of any remaining
              provisions. There is no joint venture, partnership, employment or agency relationship
              created between you and us as a result of these Legal Terms.
            </P>
          </Section>

          <Section id="contact" title="24. Contact Us">
            <P>
              In order to resolve a complaint regarding the Services or to receive further
              information regarding use of the Services, please contact us at:
            </P>
            <address className="not-italic mb-4" style={{ color: "var(--text-primary)" }}>
              <strong>Up 2 Code Inc.</strong>
              <br />
              4751 21st Ave NE, 105
              <br />
              Seattle, WA 98105
              <br />
              United States
              <br />
              Phone: 805-630-1611
              <br />
              <ExtLink href="mailto:esmith.marc@gmail.com">esmith.marc@gmail.com</ExtLink>
            </address>
          </Section>
        </article>
      </div>
    </div>
  );
}

// --- Helper components ---

function H2({ children }: { children: React.ReactNode }) {
  return (
    <h2
      className="text-xl font-bold mt-8 mb-3"
      style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}
    >
      {children}
    </h2>
  );
}

function H3({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-base font-semibold mt-5 mb-2" style={{ color: "var(--text-primary)" }}>
      {children}
    </h3>
  );
}

function P({ children }: { children: React.ReactNode }) {
  return <p className="mb-3">{children}</p>;
}

function Em({ children }: { children: React.ReactNode }) {
  return <strong style={{ color: "var(--text-primary)" }}>{children}</strong>;
}

function ExtLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} className="hover:underline" style={{ color: "var(--accent-bright)" }}>
      {children}
    </a>
  );
}

function Toc({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} className="hover:underline" style={{ color: "var(--accent-bright)" }}>
      {children}
    </a>
  );
}

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-24">
      <H2>{title}</H2>
      {children}
    </section>
  );
}
